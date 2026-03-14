"""
backfill_dates.py — 回填源码文件修改日期到已有的 scan-output 报告中。

功能：
1. 备份整个 scan-output 目录为 zip
2. 扫描原始源码目录，获取每个项目的源码文件修改日期范围
3. 在 detail 报告的 Section 1 中插入 Oldest/Newest Source File 行
4. 在 index.md 表格中添加 Last Modified 列
5. 重新生成所有 HTML

用法：
  python backfill_dates.py d:/projects/scan-output [--dry-run] [--no-backup] [--no-html]
"""

import os
import sys
import re
import zipfile
import shutil
from datetime import datetime

# ── 源码扩展名（与 scanner.py 保持一致）──
SOURCE_EXTS = {
    '.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx',
    '.java', '.kt', '.aidl',
    '.m', '.mm', '.swift',
    '.ts', '.tsx', '.js', '.jsx', '.vue', '.svelte',
    '.css', '.scss', '.less',
}

# ── 噪声目录（跳过）──
NOISE_DIRS = {
    ".git", ".svn", ".hg", ".vs", ".idea", ".vscode", "__pycache__",
    "obj", "tmp", "temp",
    "Debug", "Release", "x64", "x86", "ipch",
    "cmake-build-debug", "cmake-build-release",
    ".gradle", "build", "target", ".apt_generated", "generated",
    "DerivedData", "Pods", ".build", "xcuserdata",
    "node_modules", "dist", ".next", ".nuxt", ".output", "coverage",
}

# ── 三方库容器名 ──
THIRDPARTY_CONTAINERS = {
    "3party", "3rd_party", "third_party", "thirdparty", "vendor",
    "external", "deps", "libs", "Pods",
}


def scan_source_dates(dir_path):
    """扫描目录下所有源码文件的 mtime，返回 (oldest_date, newest_date)，格式 'YYYY-MM-DD'。"""
    if not os.path.isdir(dir_path):
        return '', ''
    oldest_mt = float('inf')
    newest_mt = 0.0
    for dirpath, dirnames, filenames in os.walk(dir_path):
        # 过滤噪声/三方库目录
        dirnames[:] = [d for d in dirnames
                       if d not in NOISE_DIRS
                       and d.lower() not in THIRDPARTY_CONTAINERS
                       and not d.startswith('.')]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in SOURCE_EXTS:
                fp = os.path.join(dirpath, f)
                try:
                    mt = os.stat(fp).st_mtime
                except OSError:
                    continue
                if mt > 0:
                    if mt < oldest_mt:
                        oldest_mt = mt
                    if mt > newest_mt:
                        newest_mt = mt
    oldest = datetime.fromtimestamp(oldest_mt).strftime('%Y-%m-%d') if oldest_mt < float('inf') else ''
    newest = datetime.fromtimestamp(newest_mt).strftime('%Y-%m-%d') if newest_mt > 0 else ''
    return oldest, newest


def extract_target(md_text):
    """从报告中提取 Target 路径。"""
    m = re.search(r'\*\*Target\*\*[：:]\s*`?([^`\n]+)`?', md_text)
    if m:
        return m.group(1).strip()
    m = re.search(r'\*\*目标\*\*[：:]\s*`?([^`\n]+)`?', md_text)
    if m:
        return m.group(1).strip()
    return ''


def patch_detail_report(md_text, oldest, newest):
    """在 detail 报告的 Section 1 表格中插入日期行。返回修改后的文本。"""
    if not oldest and not newest:
        return md_text

    # 找到 "Project Code Ratio" 行，在其后插入日期行
    lines = md_text.split('\n')
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if not inserted and 'Project Code Ratio' in line and '|' in line:
            if oldest:
                new_lines.append(f'| Oldest Source File | {oldest} |')
            if newest:
                new_lines.append(f'| Newest Source File | {newest} |')
            inserted = True

    if not inserted:
        # 备用：在 "## 2." 之前插入
        new_lines = []
        for line in lines:
            if not inserted and line.startswith('## 2.'):
                if oldest:
                    new_lines.append(f'| Oldest Source File | {oldest} |')
                if newest:
                    new_lines.append(f'| Newest Source File | {newest} |')
                new_lines.append('')
                inserted = True
            new_lines.append(line)

    return '\n'.join(new_lines)


def patch_index_report(md_text, date_map):
    """
    在 index.md 表格中添加 Last Modified 列。
    date_map: {project_name: newest_date} 字典。
    """
    lines = md_text.split('\n')
    new_lines = []
    in_table = False
    header_done = False
    separator_done = False

    for line in lines:
        stripped = line.strip()

        # 检测表格头（含 Project 和 Tech Stack 列但没有 Last Modified）
        if (not in_table and '|' in stripped and 'Project' in stripped
                and 'Tech Stack' in stripped and 'Last Modified' not in stripped):
            in_table = True
            header_done = False
            separator_done = False

        if in_table and '|' in stripped:
            if not header_done:
                # 表头行：追加 Last Modified 列
                new_lines.append(stripped.rstrip() + ' Last Modified |')
                header_done = True
                continue
            elif not separator_done:
                # 分隔行：追加列分隔
                new_lines.append(stripped.rstrip() + '--------------|')
                separator_done = True
                continue
            elif stripped.startswith('|'):
                # 数据行：提取项目名，查找日期
                cells = [c.strip() for c in stripped.split('|') if c.strip()]
                if cells:
                    proj_name = cells[0]
                    # 提取 [name](path) 中的 name
                    link_m = re.match(r'\[(.+?)\]', proj_name)
                    if link_m:
                        proj_name = link_m.group(1)
                    date_val = date_map.get(proj_name, '-')
                    new_lines.append(stripped.rstrip() + f' {date_val} |')
                    continue
                else:
                    in_table = False
        elif in_table:
            # 表格结束
            in_table = False

        new_lines.append(line)

    return '\n'.join(new_lines)


def backup_scan_output(scan_dir):
    """将 scan-output 备份为 zip 文件。"""
    parent = os.path.dirname(scan_dir.rstrip('/\\'))
    basename = os.path.basename(scan_dir.rstrip('/\\'))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_path = os.path.join(parent, f'{basename}_backup_{timestamp}.zip')

    print(f'备份 {scan_dir} → {zip_path} ...')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(scan_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                arcname = os.path.relpath(fp, parent)
                zf.write(fp, arcname)

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f'备份完成: {zip_path} ({size_mb:.1f} MB)')
    return zip_path


def process_scan_output(scan_dir, dry_run=False, no_backup=False, no_html=False):
    """主流程。"""
    scan_dir = os.path.abspath(scan_dir)

    if not os.path.isdir(scan_dir):
        print(f'错误: 目录不存在: {scan_dir}')
        sys.exit(1)

    # Step 1: 备份
    if not no_backup and not dry_run:
        backup_scan_output(scan_dir)

    # Step 2: 收集所有 .md 文件
    detail_files = []  # (md_path, target_path)
    index_files = []   # (md_path, md_dir)

    for dirpath, dirnames, filenames in os.walk(scan_dir):
        for f in filenames:
            if not f.endswith('.md'):
                continue
            fp = os.path.join(dirpath, f)
            if f == 'index.md':
                index_files.append((fp, dirpath))
            else:
                detail_files.append(fp)

    print(f'找到 {len(detail_files)} 个详情报告, {len(index_files)} 个索引文件')

    # Step 3: 处理详情报告 — 扫描源码目录获取日期，写入
    # 缓存: target_path → (oldest, newest) 避免重复扫描
    date_cache = {}
    patched_detail = 0
    skipped_detail = 0
    missing_target = 0

    for i, md_path in enumerate(detail_files):
        with open(md_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # 已有日期则跳过
        if 'Oldest Source File' in text or 'Newest Source File' in text:
            skipped_detail += 1
            continue

        target = extract_target(text)
        if not target:
            missing_target += 1
            continue

        # 规范化路径
        target = os.path.normpath(target)

        if target in date_cache:
            oldest, newest = date_cache[target]
        else:
            if os.path.isdir(target):
                oldest, newest = scan_source_dates(target)
            else:
                oldest, newest = '', ''
            date_cache[target] = (oldest, newest)

        if not oldest and not newest:
            skipped_detail += 1
            continue

        new_text = patch_detail_report(text, oldest, newest)
        if new_text != text:
            if dry_run:
                print(f'  [DRY] {os.path.relpath(md_path, scan_dir)}: {oldest} ~ {newest}')
            else:
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(new_text)
            patched_detail += 1

        # 进度显示
        if (i + 1) % 100 == 0:
            print(f'  详情报告进度: {i + 1}/{len(detail_files)}')

    print(f'详情报告: 已修改 {patched_detail}, 跳过 {skipped_detail}, 无Target {missing_target}')

    # Step 4: 处理索引文件 — 需要知道每个子项目的日期
    # 构建 project_name → newest_date 映射（从已处理的 detail 报告中读取）
    patched_index = 0

    for idx_path, idx_dir in index_files:
        with open(idx_path, 'r', encoding='utf-8') as f:
            text = f.read()

        # 已有 Last Modified 列则跳过
        if 'Last Modified' in text:
            skipped_detail += 1
            continue

        # 提取此 index 的 target 路径
        idx_target = extract_target(text)
        if not idx_target:
            continue
        idx_target = os.path.normpath(idx_target)

        # 解析表格中的子项目名，扫描对应目录获取日期
        date_map = {}
        m = re.search(r'\|(.+?\|)\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', text)
        if m:
            for line in m.group(2).strip().split('\n'):
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if not cells:
                    continue
                name = cells[0]
                link_m = re.match(r'\[(.+?)\]', name)
                proj_name = link_m.group(1) if link_m else name

                # 对应的源码目录
                src_dir = os.path.join(idx_target, proj_name)
                src_dir = os.path.normpath(src_dir)

                if src_dir in date_cache:
                    _, newest = date_cache[src_dir]
                elif os.path.isdir(src_dir):
                    oldest, newest = scan_source_dates(src_dir)
                    date_cache[src_dir] = (oldest, newest)
                else:
                    newest = ''

                date_map[proj_name] = newest if newest else '-'

        if not date_map:
            continue

        new_text = patch_index_report(text, date_map)
        if new_text != text:
            if dry_run:
                print(f'  [DRY] INDEX: {os.path.relpath(idx_path, scan_dir)}')
            else:
                with open(idx_path, 'w', encoding='utf-8') as f:
                    f.write(new_text)
            patched_index += 1

    print(f'索引文件: 已修改 {patched_index}')

    # Step 5: 重新生成 HTML
    if not no_html and not dry_run:
        print('\n重新生成 HTML ...')
        regen_html(scan_dir)

    print('\n完成!')


def regen_html(scan_dir):
    """重新生成所有 HTML 文件。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gen_html = os.path.join(script_dir, 'gen_html.py')

    if not os.path.isfile(gen_html):
        print(f'  警告: gen_html.py 未找到: {gen_html}')
        return

    import subprocess

    # 收集所有 .md 文件
    md_files = []
    for dirpath, dirnames, filenames in os.walk(scan_dir):
        for f in filenames:
            if f.endswith('.md'):
                md_files.append(os.path.join(dirpath, f))

    # 先处理非 index 文件（详情报告），再处理 index 文件
    detail_mds = [f for f in md_files if os.path.basename(f) != 'index.md']
    index_mds = [f for f in md_files if os.path.basename(f) == 'index.md']

    total = len(detail_mds) + len(index_mds)
    done = 0
    errors = 0

    for md in detail_mds + index_mds:
        done += 1
        try:
            result = subprocess.run(
                [sys.executable, gen_html, md],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                errors += 1
                if errors <= 5:
                    print(f'  错误 [{done}/{total}]: {os.path.relpath(md, scan_dir)}')
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'  异常 [{done}/{total}]: {e}')

        if done % 100 == 0:
            print(f'  HTML 进度: {done}/{total}')

    print(f'  HTML 生成完成: {done} 个, {errors} 个错误')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='回填源码修改日期到已有 scan-output 报告')
    parser.add_argument('scan_dir', help='scan-output 目录路径')
    parser.add_argument('--dry-run', action='store_true', help='仅显示将要修改的文件，不实际写入')
    parser.add_argument('--no-backup', action='store_true', help='跳过备份步骤')
    parser.add_argument('--no-html', action='store_true', help='不重新生成 HTML')
    args = parser.parse_args()

    process_scan_output(args.scan_dir, dry_run=args.dry_run, no_backup=args.no_backup, no_html=args.no_html)
