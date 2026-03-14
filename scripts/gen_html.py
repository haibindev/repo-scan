#!/usr/bin/env python3
"""
gen_html.py — 将 repo-scan 生成的 markdown 审计报告转为可视化 HTML 页面。

用法:
  python gen_html.py <report.md> [-o output.html] [--open]

无 -o 时默认输出到 report.md 同目录下的 report.html。
--open 自动用浏览器打开。
"""

import argparse
import json
import os
import re
import sys
import platform
import subprocess

from parsers import parse_report, parse_index_report

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, '..', 'templates', 'report.html')
INDEX_TEMPLATE_PATH = os.path.join(SCRIPT_DIR, '..', 'templates', 'index.html')


def generate_html(report, template_path, output_path):
    """将 REPORT 数据注入 HTML 模板并写出"""
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # 序列化 REPORT 为 JS (ensure_ascii=False 保持中文)
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    # 替换模板中 __REPORT_BEGIN__ ... __REPORT_END__ 之间的内容
    # 注意：用 lambda 而非字符串替换，避免 re.sub 把 JSON 中的 \\ 处理成 \
    replacement = '// __REPORT_BEGIN__\nconst REPORT = ' + report_json + ';\n// __REPORT_END__'
    pattern = r'// __REPORT_BEGIN__\n.*?// __REPORT_END__'
    html = re.sub(pattern, lambda _: replacement, template, flags=re.DOTALL)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path

def main():
    parser = argparse.ArgumentParser(description='将 repo-scan markdown 报告转为 HTML 可视化页面')
    parser.add_argument('report', help='repo-scan 输出的 markdown 报告文件路径（index.md 自动使用汇总模板）')
    parser.add_argument('-o', '--output', help='输出 HTML 路径')
    parser.add_argument('-t', '--template', default='', help='HTML 模板路径（留空则自动选择）')
    parser.add_argument('--open', action='store_true', help='生成后自动打开浏览器')
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print(f'错误: 报告文件不存在: {args.report}', file=sys.stderr)
        sys.exit(1)

    # 自动检测模式：文件名为 index.md → 汇总模式
    # 例外：若 index.md 没有子项目表格（Project/Build System 列），
    # 说明这是 L4 子目录的单模块报告，应使用 report 模板而非 index 模板。
    # 注意：L3 index.md 可能同时含 Deep 分析章节 + 子项目表格，应保持 index 模式。
    is_filename_index = os.path.basename(args.report).lower() == 'index.md'
    if is_filename_index:
        with open(args.report, 'r', encoding='utf-8', errors='ignore') as _f:
            _peek = _f.read(4096)
        # 子项目表格特征：表头含 Project/Build System/Source Files 等列
        _has_subproject_table = bool(
            re.search(r'\|\s*(?:Project|子项目|名称)\s*\|', _peek) or
            re.search(r'\|\s*Build System\s*\|', _peek)
        )
        is_index = _has_subproject_table  # 有子项目表 → 汇总索引；无 → 单模块报告
    else:
        is_index = False

    template = args.template
    if not template:
        template = INDEX_TEMPLATE_PATH if is_index else TEMPLATE_PATH

    if not os.path.exists(template):
        print(f'错误: 模板文件不存在: {template}', file=sys.stderr)
        sys.exit(1)

    report_dir = os.path.dirname(os.path.abspath(args.report))

    if is_index:
        output = args.output or os.path.join(report_dir, 'index.html')
        print(f'解析汇总索引: {args.report}')
        report = parse_index_report(args.report)
        print(f'  子项目: {len(report["subprojects"])} 个')
        print(f'  能力重叠: {len(report["overlaps"])} 条')
        print(f'  依赖拓扑: {len(report["topology"])} 条')
        print(f'  修正判决: {len(report["revisions"])} 条')
    else:
        output = args.output or os.path.join(report_dir, 'index.html' if is_filename_index else 'report.html')
        print(f'解析报告: {args.report}')
        report = parse_report(args.report)
        print(f'  项目: {report["title"]}')
        print(f'  模块: {len(report["modules"])} 个')
        print(f'  定级表: {len(report["triage"])} 行')
        print(f'  三方依赖: {len(report["thirdPartyDeps"])} 个')

    generate_html(report, template, output)
    print(f'HTML 已生成: {output}')

    if args.open:
        abs_path = os.path.abspath(output)
        if platform.system() == 'Windows':
            os.startfile(abs_path)
        elif platform.system() == 'Darwin':
            subprocess.run(['open', abs_path])
        else:
            subprocess.run(['xdg-open', abs_path])

if __name__ == '__main__':
    main()
