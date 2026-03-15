#!/usr/bin/env python3
"""
cleanup.py — 清理 scan-output 目录中的临时文件，保留最终报告和人工决策。

用法:
  python cleanup.py <scan-output-dir> [--dry-run] [--keep-dual-raw]

默认清理:
  - 预扫描生成的子目录（每个模块的 index.md/cpp.md 等）
  - batch*-full-report.md（中间批次报告，数据已合并到 index.md）
  - .dual-scan/prompt-batch*.txt（Agent-2 输入提示词）
  - .dual-scan/ 中的空文件（失败的批次）
  - 旧的 report.html（被 index.html 替代）

保留:
  - index.md（最终报告）
  - index.html / dual-scan.html（生成的可视化页面）
  - .dual-scan/result-batch*.txt（Agent-2 原始分析结果，解析器需要）
  - .dual-scan/human-decisions.json（人工决策，永不删除）

选项:
  --dry-run       仅预览要删除的内容，不实际删除
  --keep-dual-raw 保留 .dual-scan/ 中的 prompt 文件
  --all           同时清理 .dual-scan/result-batch*.txt（谨慎：删后 dual-scan.html 无法重新生成）
"""

import argparse
import os
import shutil
import sys


def get_cleanup_targets(scan_dir, keep_dual_raw=False, clean_all=False):
    """扫描目录，返回待清理的文件和目录列表"""
    to_delete_files = []
    to_delete_dirs = []

    if not os.path.isdir(scan_dir):
        print(f'错误: 目录不存在: {scan_dir}', file=sys.stderr)
        sys.exit(1)

    # 保护列表 — 这些文件/目录永远不删除
    protected_files = {'index.md', 'index.html', 'dual-scan.html'}
    protected_dirs = set()

    # 1. 预扫描生成的子模块目录（含 index.md 或 cpp.md 等）
    for entry in os.listdir(scan_dir):
        full = os.path.join(scan_dir, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith('.'):
            continue  # .dual-scan 单独处理
        if entry in protected_dirs:
            continue
        # 检查是否为预扫描子目录（含 index.md 或 *.md）
        sub_files = os.listdir(full)
        is_prescan = any(f.endswith('.md') for f in sub_files)
        if is_prescan:
            to_delete_dirs.append(full)

    # 2. 中间批次报告
    for entry in os.listdir(scan_dir):
        full = os.path.join(scan_dir, entry)
        if not os.path.isfile(full):
            continue
        if entry in protected_files:
            continue
        # batch*-full-report.md
        if entry.startswith('batch') and entry.endswith('-full-report.md'):
            to_delete_files.append(full)
        # 旧的 report.html
        if entry == 'report.html':
            to_delete_files.append(full)

    # 3. .dual-scan 目录中的临时文件
    dual_dir = os.path.join(scan_dir, '.dual-scan')
    if os.path.isdir(dual_dir):
        for entry in os.listdir(dual_dir):
            full = os.path.join(dual_dir, entry)
            if not os.path.isfile(full):
                continue
            # 永不删除人工决策文件
            if entry == 'human-decisions.json':
                continue
            # prompt 文件
            if entry.startswith('prompt-'):
                if not keep_dual_raw:
                    to_delete_files.append(full)
                continue
            # 空文件（失败的批次）
            if os.path.getsize(full) == 0:
                to_delete_files.append(full)
                continue
            # result 文件（仅 --all 模式清理）
            if entry.startswith('result-') and clean_all:
                to_delete_files.append(full)

    return to_delete_files, to_delete_dirs


def format_size(size):
    if size < 1024:
        return f'{size} B'
    elif size < 1024 * 1024:
        return f'{size/1024:.1f} KB'
    else:
        return f'{size/1024/1024:.1f} MB'


def main():
    parser = argparse.ArgumentParser(description='清理 scan-output 临时文件')
    parser.add_argument('scan_dir', help='scan-output 目录路径')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，不实际删除')
    parser.add_argument('--keep-dual-raw', action='store_true', help='保留 .dual-scan 中的 prompt 文件')
    parser.add_argument('--all', action='store_true', help='同时清理 result-batch*.txt（谨慎）')
    args = parser.parse_args()

    files, dirs = get_cleanup_targets(args.scan_dir, args.keep_dual_raw, args.all)

    if not files and not dirs:
        print('无需清理的临时文件。')
        return

    total_size = 0

    if dirs:
        print(f'\n待删除目录 ({len(dirs)} 个):')
        for d in sorted(dirs):
            dir_size = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fns in os.walk(d)
                for f in fns
            )
            total_size += dir_size
            print(f'  [DIR]  {os.path.relpath(d, args.scan_dir)}/  ({format_size(dir_size)})')

    if files:
        print(f'\n待删除文件 ({len(files)} 个):')
        for f in sorted(files):
            fsize = os.path.getsize(f)
            total_size += fsize
            print(f'  [FILE] {os.path.relpath(f, args.scan_dir)}  ({format_size(fsize)})')

    print(f'\n合计: {len(dirs)} 个目录 + {len(files)} 个文件，释放 {format_size(total_size)}')

    if args.dry_run:
        print('\n(--dry-run 模式，未实际删除)')
        return

    # 执行删除
    for d in dirs:
        shutil.rmtree(d)
    for f in files:
        os.remove(f)

    print('\n清理完成。')

    # 打印保留的文件
    remaining = []
    for entry in sorted(os.listdir(args.scan_dir)):
        full = os.path.join(args.scan_dir, entry)
        if os.path.isfile(full):
            remaining.append(entry)
    dual_dir = os.path.join(args.scan_dir, '.dual-scan')
    if os.path.isdir(dual_dir):
        for entry in sorted(os.listdir(dual_dir)):
            remaining.append(f'.dual-scan/{entry}')

    print('\n保留的文件:')
    for r in remaining:
        print(f'  {r}')


if __name__ == '__main__':
    main()
