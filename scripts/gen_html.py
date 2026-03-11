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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, '..', 'templates', 'report.html')
INDEX_TEMPLATE_PATH = os.path.join(SCRIPT_DIR, '..', 'templates', 'index.html')

# ─── markdown 工具 ──────────────────────────────────────────

def strip_bold(s):
    """去除 **text** 标记"""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', s)

def strip_backtick(s):
    """去除 `code` 标记"""
    return re.sub(r'`(.+?)`', r'\1', s)

def md_to_html(s):
    """简易 markdown → HTML: **bold**, `code`，并对评估关键词着色"""
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'`(.+?)`', r'<code>\1</code>', s)
    # 关键词着色 — 单次扫描（最长优先）避免短词嵌套替换长词已生成的 span
    RED_KW = ['极度过时', '严重冗余', '完全冗余', 'God Object', '彻底淘汰', '严重过时', '重塑提取']
    YLW_KW = ['过时', '体积异常', '双副本', '三副本', '重复副本', '硬编码', '已弃用', '应精简',
              '臃肿', '提纯合并', '职责过重', '全局变量', '竞态']
    GRN_KW = ['核心基石']
    kw_color = ([(kw, '--red') for kw in RED_KW] +
                [(kw, '--yellow') for kw in YLW_KW] +
                [(kw, '--green') for kw in GRN_KW])
    kw_color.sort(key=lambda x: -len(x[0]))  # 最长优先，避免短词先匹配
    color_map = {kw: color for kw, color in kw_color}
    pattern = '|'.join(re.escape(kw) for kw, _ in kw_color)
    s = re.sub(pattern, lambda m: f'<span style="color:var({color_map[m.group(0)]})">{m.group(0)}</span>', s)
    return s

def clean(s):
    """清理字段文本"""
    return s.strip().rstrip('|').strip()

# ─── 解析器 ──────────────────────────────────────────────────

def parse_header(text):
    """解析头部元数据"""
    info = {}
    m = re.search(r'\*\*项目\*\*:\s*`?([^`\n]+)`?', text)
    if m: info['project'] = m.group(1).strip()
    m = re.search(r'\*\*路径\*\*:\s*`?([^`\n]+)`?', text)
    if m: info['target'] = m.group(1).strip()
    m = re.search(r'\*\*审计日期\*\*:\s*(\S+)', text)
    if m: info['date'] = m.group(1).strip()
    m = re.search(r'\*\*项目概貌\*\*:\s*(.+?)(?:\n|$)', text)
    if m: info['desc'] = m.group(1).strip()
    return info

def compress_tree(raw, max_files=5):
    """
    压缩原始树：每个顶级目录最多保留 max_files 个文件行。
    规则：
      - 目录行（├/└── xxx/）始终保留
      - 含 [3rd-party 或废弃/遗留/冗余标记的行始终保留
      - 空分隔行（只含 │）始终保留
      - 其余文件行按出现顺序保留前 max_files 个，多余的合并成一行省略提示
    """
    DEAD_KW = {'废弃', '遗留', '冗余', '应清理', '构建产物', '空文件', '占位', '重复'}

    lines = raw.split('\n')
    result = []
    file_count = 0   # 当前目录文件计数
    skipped = 0      # 当前目录已跳过的文件数

    def flush_skipped():
        nonlocal skipped
        if skipped > 0:
            result.append(f'│   └── ... ({skipped} 个文件省略)')
            skipped = 0

    for line in lines:
        # 目录头行：├── xxx/ 或 └── xxx/（可能前缀有 │）
        # 注意：要求 / 后紧跟空白或行尾，避免把 Lock.h/cpp 这样的文件名误判为目录
        is_dir = bool(re.search(r'[├└]── [^\s#\[]+/(?=\s|$)', line))
        # 三方库标记行
        is_3rd = '[3rd-party' in line
        # 废弃/遗留标记行
        is_dead = any(kw in line for kw in DEAD_KW)
        # 纯分隔行（只有 │ 和空格）
        is_sep = bool(re.match(r'^[│\s]*$', line))
        # 文件行（有缩进的 ├/└）
        is_file = bool(re.search(r'│\s+[├└]', line)) and not is_dir

        if is_dir:
            flush_skipped()
            file_count = 0
            result.append(line)
        elif is_3rd or is_dead:
            result.append(line)
        elif is_sep:
            flush_skipped()
            result.append(line)
        elif is_file:
            if file_count < max_files:
                result.append(line)
                file_count += 1
            else:
                skipped += 1
        else:
            flush_skipped()
            result.append(line)

    flush_skipped()
    return '\n'.join(result)


def parse_tree(text):
    """提取资产总览树，压缩后加 HTML 高亮"""
    m = re.search(r'```text\s*\n(.*?)```', text, re.DOTALL)
    if not m:
        return ''
    raw = m.group(1).rstrip()
    compressed = compress_tree(raw, max_files=5)

    # HTML 转义
    tree = compressed.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # 高亮目录名
    tree = re.sub(r'(\S+/)', r'<span class="dir">\1</span>', tree)
    # 高亮三方库标记
    tree = re.sub(r'(\[3rd-party[^\]]*\])', r'<span class="tag-3rd">\1</span>', tree)
    # 高亮废弃/遗留注释（# 或 -- 开头且含关键词）
    DEAD_KW_RE = '废弃|遗留|冗余|应清理|空文件|占位|重复副本|构建产物|应删除'
    tree = re.sub(
        r'((?:#|--)\s[^\n]*(?:' + DEAD_KW_RE + r')[^\n]*)',
        r'<span class="tag-dead">\1</span>', tree)
    # 高亮普通注释（未被上面匹配的 # 注释）
    tree = re.sub(r'(?<!span>)(#\s[^\n<]+)', r'<span class="tag-core">\1</span>', tree)
    return tree

def parse_modules(text):
    """解析模块级描述"""
    modules = []
    # 按 ### 分割
    parts = re.split(r'\n### \d+\.\d+\s+', text)
    for part in parts[1:]:  # 跳过第一个空段
        mod = {}
        # 标题行: name — description
        first_line = part.split('\n', 1)[0]
        m = re.match(r'(.+?)\s*[—\-]+\s*(.*)', first_line)
        if m:
            mod['name'] = m.group(1).strip()
            mod['subtitle'] = m.group(2).strip()
        else:
            mod['name'] = first_line.strip()
            mod['subtitle'] = ''

        # 各字段
        def extract_field(pattern, default=''):
            match = re.search(pattern, part, re.DOTALL)
            return match.group(1).strip() if match else default

        mod['path'] = strip_backtick(extract_field(r'\*\*物理落点\*\*:\s*(.+?)(?:\n-|\n\n|$)'))
        mod['function'] = md_to_html(extract_field(r'\*\*功能全貌矩阵\*\*:\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        # 核心代码模块 — 只提取类名（backtick 包裹），丢弃解释句，用 / 连接
        core_match = re.search(r'\*\*内部核心代码模块\*\*:\s*\n((?:\s+-.+\n?)+)', part)
        core_raw = core_match.group(1) if core_match else \
                   extract_field(r'\*\*内部核心代码模块\*\*:\s*(.+?)(?:\n-\s\*\*|\n\n|$)')
        # 从每行提取第一个反引号类名（跳过路径类、过长描述）
        names = []
        for line in core_raw.split('\n'):
            found = re.findall(r'`([^`]{1,50})`', line)
            for n in found:
                if n not in names and not n.startswith('/') and not n.startswith('#'):
                    names.append(n)
                    break  # 每行只取第一个类名
        if names:
            mod['coreClasses'] = ' / '.join(f'<code>{n}</code>' for n in names)
        else:
            mod['coreClasses'] = md_to_html(core_raw.strip())

        mod['deps'] = md_to_html(extract_field(r'\*\*模块间依赖关系\*\*:\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        # 三方库引用 — 可能是多行列表
        tp_match = re.search(r'\*\*三方库引用\*\*:\s*\n((?:\s+-.+\n?)+)', part)
        if tp_match:
            items = re.findall(r'-\s+(.+)', tp_match.group(1))
            mod['thirdParty'] = '<br>'.join(md_to_html(i) for i in items)
        else:
            mod['thirdParty'] = md_to_html(extract_field(r'\*\*三方库引用\*\*:\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        mod['codeSize'] = md_to_html(extract_field(r'\*\*代码体量\*\*:\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        # 质量评估 — 只保留「架构合理性」和「历史包袱」，丢弃「代码活跃度」和「定论判决」
        quality_match = re.search(r'\*\*质量与技术债评估\*\*:\s*\n((?:\s+-.+\n?)+)', part)
        if quality_match:
            items = re.findall(r'-\s+(.+)', quality_match.group(1))
            kept = []
            for item in items:
                # 跳过活跃度行和判决行
                if re.search(r'^代码活跃度|^活跃度|定论判决', item.strip()):
                    continue
                # 「架构合理性」：去掉前缀标签，保留结论
                item = re.sub(r'^架构合理性[：:]\s*', '', item.strip())
                # 「历史包袱」：去掉前缀，改为"技术债:"标签
                if re.match(r'^历史包袱', item):
                    item = re.sub(r'^历史包袱[：:]\s*', '<span style="color:var(--yellow)">技术债:</span> ', item)
                kept.append(md_to_html(item))
            mod['quality'] = '<br>'.join(kept) if kept else ''
        else:
            mod['quality'] = md_to_html(extract_field(r'\*\*质量与技术债评估\*\*:\s*(.+?)(?:\n\n|$)'))

        # 判决
        verdict_match = re.search(r'定论判决[：:]\s*(\S+)', part)
        if verdict_match:
            mod['verdict'] = strip_bold(verdict_match.group(1)).strip('*').strip()
        else:
            mod['verdict'] = ''

        # 活跃度
        activity_match = re.search(r'代码活跃度[：:]\s*(.+?)(?:\n|$)', part)
        if activity_match:
            mod['activity'] = md_to_html(activity_match.group(1).strip())
        else:
            mod['activity'] = ''

        modules.append(mod)
    return modules

def parse_md_table(text, section_header):
    """解析指定章节标题下的 markdown 表格，返回 [dict, ...]"""
    # 先截取本章节文本（到下一个 ## 或 --- 为止）
    pattern = re.escape(section_header)
    sec_match = re.search(pattern + r'.*?\n', text)
    if not sec_match:
        return [], []
    start = sec_match.end()
    # 找下一个章节边界
    next_sec = re.search(r'\n---\s*\n|\n## ', text[start:])
    section_text = text[start:start + next_sec.start()] if next_sec else text[start:]

    # 在章节内找表格
    m = re.search(r'\|(.+?\|)\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', section_text)
    if not m:
        return [], []

    header_line = m.group(1)
    body = m.group(2)

    headers = [h.strip() for h in header_line.split('|') if h.strip()]
    rows = []
    for line in body.strip().split('\n'):
        cells = [clean(c) for c in line.split('|')[1:] if c.strip() or c.strip() == '']
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            rows.append(cells)

    return headers, rows

def parse_deep_analysis(text):
    """解析 Deep 级深度分析章节，返回 dict 或 None"""
    m = re.search(r'## Deep 级深度分析\s*\n(.*?)(?:\n## (?!#)|\Z)', text, re.DOTALL)
    if not m:
        return None
    section = m.group(1)
    deep = {}

    # 精读文件清单
    files_m = re.search(r'### 精读文件清单\s*\n((?:(?:\d+\.\s*|[-*]\s*).+\n?)+)', section)
    if files_m:
        deep['files'] = [re.sub(r'^[\d.]+\s*|^[-*]\s*', '', l.strip()) for l in files_m.group(1).strip().split('\n') if l.strip()]

    # 各评估子章节
    for key, zh in [('threadSafety', '线程安全评估'), ('memory', '内存管理评估'),
                     ('errorHandling', '错误处理评估'), ('apiConsistency', 'API设计一致性'),
                     ('apiConsistency', 'API 设计一致性'),
                     ('extraFindings', 'Deep级补充发现'), ('extraFindings', 'Deep 级补充发现')]:
        pat = r'### ' + re.escape(zh) + r'\s*\n(.*?)(?=\n### |\Z)'
        sm = re.search(pat, section, re.DOTALL)
        if sm and key not in deep:
            raw = sm.group(1).strip()
            # 转换 markdown 列表为 HTML
            items = []
            current = ''
            for line in raw.split('\n'):
                line_stripped = line.strip()
                if re.match(r'^[-*]\s+\*\*|^\d+\.\s+\*\*|^[-*]\s+', line_stripped):
                    if current:
                        items.append(md_to_html(current))
                    current = re.sub(r'^[-*]\s+|^\d+\.\s+', '', line_stripped)
                elif line_stripped and current:
                    current += ' ' + line_stripped
                elif line_stripped:
                    current = line_stripped
            if current:
                items.append(md_to_html(current))
            deep[key] = items

    return deep if deep else None


def parse_summary(text):
    """解析审计总结"""
    summary = {}
    # 找到审计总结区域
    m = re.search(r'## 审计总结\s*\n(.*)', text, re.DOTALL)
    if not m:
        return summary
    section = m.group(1)

    for key, zh in [('profile', '项目整体画像'), ('risks', '关键风险'), ('actions', '优先行动建议')]:
        pattern = r'### ' + zh + r'\s*\n((?:\d+\.\s*.+\n?|- .+\n?|  .+\n?)*)'
        match = re.search(pattern, section)
        if match:
            items = []
            for line in match.group(1).strip().split('\n'):
                line = re.sub(r'^\d+\.\s*', '', line)
                line = re.sub(r'^-\s*', '', line)
                line = strip_bold(line).strip()
                if line:
                    items.append(line)
            summary[key] = items

    return summary

def estimate_stack(modules, text):
    """从报告推断技术栈占比"""
    # 尝试从审计总结中提取
    cpp_m = re.search(r'C/C\+\+.*?(\d+)\s*文件', text)
    java_m = re.search(r'Java.*?(\d+)\s*文件', text)
    ios_m = re.search(r'iOS.*?(\d+)\s*文件', text)
    web_m = re.search(r'Web.*?(\d+)\s*文件', text)

    cpp = int(cpp_m.group(1)) if cpp_m else 0
    java = int(java_m.group(1)) if java_m else 0
    ios = int(ios_m.group(1)) if ios_m else 0
    web = int(web_m.group(1)) if web_m else 0

    total = cpp + java + ios + web
    if total == 0:
        return {'cpp': 100, 'java': 0, 'ios': 0, 'web': 0, 'other': 0}

    other = 0
    cpp_pct = round(cpp / total * 100)
    java_pct = round(java / total * 100)
    ios_pct = round(ios / total * 100)
    web_pct = round(web / total * 100)
    other = 100 - cpp_pct - java_pct - ios_pct - web_pct

    return {'cpp': cpp_pct, 'java': java_pct, 'ios': ios_pct, 'web': web_pct, 'other': max(0, other)}

def build_stats(header, modules, text):
    """构建统计卡片"""
    stats = []

    # 代码规模
    m = re.search(r'(\d+)\s*文件\s*/\s*约?\s*(\d+\s*\w+)\s*纯代码', text)
    if m:
        stats.append({'label': '项目自有源码', 'value': m.group(1) + ' 文件', 'color': 'green'})
        stats.append({'label': '纯代码体积', 'value': '~' + m.group(2), 'color': 'green'})

    # 三方库总体积 — 专门在"审计总结"章节里找，避免匹配到模块描述里的局部体积
    summary_start = text.find('## 审计总结')
    search_scope = text[summary_start:] if summary_start >= 0 else text
    m = re.search(r'三方库约\s*(\d+\s*[KMGT]?B)', search_scope)
    if not m:
        m = re.search(r'三方库约\s*(\d+\s*\w+)', search_scope)
    if m:
        stats.append({'label': '三方库体积', 'value': '~' + m.group(1), 'color': 'yellow'})

    # 按判决统计
    verdicts = {}
    for mod in modules:
        v = mod.get('verdict', '')
        if v:
            verdicts[v] = verdicts.get(v, 0) + 1

    stats.append({'label': '模块总数', 'value': str(len(modules)), 'color': 'accent'})
    verdict_colors = {'核心基石': 'green', '提纯合并': 'yellow', '重塑提取': 'purple', '彻底淘汰': 'red'}
    for v, count in verdicts.items():
        stats.append({'label': v, 'value': str(count), 'color': verdict_colors.get(v, 'accent')})

    return stats

# ─── 主流程 ──────────────────────────────────────────────────

def parse_report(md_path):
    """解析 markdown 报告, 返回 REPORT dict"""
    with open(md_path, 'r', encoding='utf-8') as f:
        text = f.read()

    header = parse_header(text)
    tree = parse_tree(text)
    modules = parse_modules(text)
    summary = parse_summary(text)
    deep = parse_deep_analysis(text)
    stack = estimate_stack(modules, text)
    stats = build_stats(header, modules, text)

    # 资产定级表
    triage_headers, triage_rows = parse_md_table(text, '## 三、资产定级表')
    triage = []
    for row in triage_rows:
        while len(row) < 7:
            row.append('')
        triage.append({
            'module': strip_backtick(strip_bold(row[0])),
            'function': md_to_html(row[1]),
            'thirdParty': md_to_html(row[2]),
            'deps': md_to_html(row[3]),
            'activity': md_to_html(row[4]),
            'quality': md_to_html(row[5]),
            'verdict': strip_bold(row[6]).strip('*'),
        })

    # 三方依赖表
    deps_headers, deps_rows = parse_md_table(text, '## 附录')
    third_party = []
    for row in deps_rows:
        while len(row) < 7:
            row.append('')
        third_party.append({
            'name': strip_backtick(strip_bold(row[0])),
            'version': md_to_html(row[1]),
            'location': md_to_html(row[2]),
            'size': md_to_html(row[3]),
            'usedBy': md_to_html(row[4]),
            'usage': md_to_html(row[5]),
            'assessment': md_to_html(row[6]),
        })

    report = {
        'title': (header.get('project', '') + ' 源码资产审计报告').strip(),
        'target': header.get('target', ''),
        'date': header.get('date', ''),
        'desc': header.get('desc', ''),
        'stats': stats,
        'stack': stack,
        'tree': tree,
        'modules': [{
            'name': m['name'],
            'path': m.get('path', ''),
            'verdict': m.get('verdict', ''),
            'function': m.get('function', ''),
            'coreClasses': m.get('coreClasses', ''),
            'deps': m.get('deps', ''),
            'thirdParty': m.get('thirdParty', ''),
            'codeSize': m.get('codeSize', ''),
            'quality': m.get('quality', ''),
            'activity': m.get('activity', ''),
        } for m in modules],
        'triage': triage,
        'thirdPartyDeps': third_party,
        'summary': summary,
        'deep': deep,
        'hasDeep': deep is not None,
    }
    return report

# ─── index.md 解析器 ─────────────────────────────────────────

def parse_index_report(md_path):
    """解析 index.md，返回 INDEX_REPORT dict（用于 index.html 模板）"""
    with open(md_path, 'r', encoding='utf-8') as f:
        text = f.read()

    md_dir = os.path.dirname(os.path.abspath(md_path))

    # ── 头部：扫描目标和日期（兼容中英文字段名）──
    target, date, desc = '', '', ''
    m = re.search(r'\*\*(?:目标|Target)\*\*[：:]\s*`?([^`\n]+)`?', text)
    if m: target = m.group(1).strip()
    m = re.search(r'\*\*(?:扫描日期|Scan Time|Scan Date)\*\*[：:]\s*(\S+)', text)
    if m: date = m.group(1).strip()
    m = re.search(r'\*\*(?:概述|Description|Sub-projects)\*\*[：:]\s*(.+?)(?:\n|$)', text)
    if m: desc = m.group(1).strip()

    # 如果没有明确头部字段，尝试从路径提取
    if not target:
        m = re.search(r'# .+?([A-Za-z]:[^\n]+|/[^\n]+)', text)
        if m: target = m.group(1).strip()

    # ── 子项目列表（从 Markdown 表格解析）──
    # 格式: | 子项目 | 构建系统 | 文件数 | 体积 | 技术栈 | [判决列...] |
    subprojects = []
    m = re.search(r'\|(.+?\|)\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', text)
    if m:
        headers = [h.strip() for h in m.group(1).split('|') if h.strip()]
        for line in m.group(2).strip().split('\n'):
            cells = [clean(c) for c in line.split('|')[1:] if c != '']
            while cells and not cells[-1]:
                cells.pop()
            if not cells:
                continue
            proj = {}
            # 按已知列名映射（兼容中英文）
            col_map = {
                '子项目': 'name', '名称': 'name', 'Project': 'name',
                '构建系统': 'buildSystem', 'Build System': 'buildSystem',
                '文件数': 'files', '源码文件': 'files', 'Source Files': 'files',
                '体积': 'size', '代码体积': 'size', 'Source Size': 'size',
                '技术栈': 'stack', 'Tech Stack': 'stack',
            }
            verdicts_sum = {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0}
            for i, h in enumerate(headers):
                if i >= len(cells):
                    break
                key = col_map.get(h)
                if key:
                    proj[key] = strip_backtick(strip_bold(cells[i]))
                elif h in verdicts_sum:
                    try:
                        verdicts_sum[h] = int(re.search(r'\d+', cells[i]).group())
                    except Exception:
                        pass
            if not proj.get('name'):
                continue
            # 剥离 markdown 链接语法: [name](path) → name，并记录链接路径
            link_path = ''
            link_match = re.match(r'\[(.+?)\]\((.+?)\)', proj['name'])
            if link_match:
                proj['name'] = link_match.group(1)
                link_path = link_match.group(2)  # e.g. "ai/index.md"
            proj['verdicts'] = verdicts_sum
            # 关联 HTML 文件：优先用链接路径推导，否则查找 name/index.html 或 name.html
            html_file = ''
            if link_path:
                # ai/index.md → ai/index.html
                html_candidate = re.sub(r'\.md$', '.html', link_path)
                if os.path.exists(os.path.join(md_dir, html_candidate)):
                    html_file = html_candidate
            if not html_file:
                # 尝试 name/index.html
                candidate = os.path.join(proj['name'], 'index.html')
                if os.path.exists(os.path.join(md_dir, candidate)):
                    html_file = candidate
            if not html_file:
                # 尝试 name.html
                candidate = re.sub(r'[\\/:*?"<>|]', '_', proj['name']) + '.html'
                if os.path.exists(os.path.join(md_dir, candidate)):
                    html_file = candidate
            proj['htmlFile'] = html_file
            subprojects.append(proj)

    # ── 从全局资产判决汇总表补充 verdict 数据 ──
    verdict_table_m = re.search(r'## 全局资产判决汇总\s*\n.*?\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', text)
    if verdict_table_m:
        verdict_map = {}  # name → {核心基石: N, ...}
        for line in verdict_table_m.group(1).strip().split('\n'):
            cells = [clean(c) for c in line.split('|')[1:] if c != '']
            while cells and not cells[-1]:
                cells.pop()
            if not cells or len(cells) < 6:
                continue
            name = strip_backtick(strip_bold(cells[0]))
            if name.startswith('**') or name == '合计':
                continue
            # 总判决列格式: "3/8/5/9" 或 "6/4+/5/18+"
            total_col = cells[-1] if len(cells) >= 6 else ''
            parts = re.findall(r'(\d+)\+?', total_col)
            if len(parts) >= 4:
                verdict_map[name] = {
                    '核心基石': int(parts[0]),
                    '提纯合并': int(parts[1]),
                    '重塑提取': int(parts[2]),
                    '彻底淘汰': int(parts[3]),
                }
        # 将 verdict 数据合并到 subprojects
        for proj in subprojects:
            name = proj.get('name', '')
            if name in verdict_map:
                proj['verdicts'] = verdict_map[name]

    # ── 交叉审阅章节 ──
    overlaps, topology, revisions, actions = [], [], [], []

    cross_m = re.search(r'## 跨模块交叉审阅\s*\n(.*?)(?:\n## |\Z)', text, re.DOTALL)
    if cross_m:
        cross_text = cross_m.group(1)

        # 能力重叠表（兼容 3 列和 4 列格式）
        ov_h, ov_rows = parse_md_table(cross_text + '\n## END', '### 能力重叠地图')
        for row in ov_rows:
            while len(row) < 4: row.append('')
            if len(ov_h) >= 4:
                # 4 列: 能力域 | 重复模块 | 重复次数 | 建议合并路径
                overlaps.append({'capability': strip_backtick(row[0]),
                                 'modules': md_to_html(row[1]),
                                 'count': strip_backtick(row[2]),
                                 'suggestion': md_to_html(row[3])})
            else:
                # 3 列: 能力域 | 重复模块 | 建议合并路径
                overlaps.append({'capability': strip_backtick(row[0]),
                                 'modules': md_to_html(row[1]),
                                 'suggestion': md_to_html(row[2])})

        # 依赖拓扑表
        tp_h, tp_rows = parse_md_table(cross_text + '\n## END', '### 依赖拓扑')
        for row in tp_rows:
            while len(row) < 4: row.append('')
            topology.append({'level': row[0], 'module': strip_backtick(row[1]),
                             'dependents': row[2], 'note': md_to_html(row[3])})

        # 修正判决表
        rv_h, rv_rows = parse_md_table(cross_text + '\n## END', '### 修正判决')
        for row in rv_rows:
            while len(row) < 4: row.append('')
            revisions.append({'module': strip_backtick(row[0]),
                              'original': strip_bold(row[1]),
                              'revised': strip_bold(row[2]),
                              'reason': md_to_html(row[3])})

        # 行动优先级（有序列表，兼容多行条目——以数字开头为新条目，否则续接上一条）
        act_m = re.search(r'### 重构行动优先级\s*\n((?:[ \t]*\d+\..+\n?|[ \t]+-.+\n?|[ \t]+[^\n]+\n?)+)', cross_text)
        if act_m:
            raw_lines = act_m.group(1).strip().split('\n')
            for l in raw_lines:
                l = l.strip()
                if re.match(r'^\d+\.', l):
                    actions.append(re.sub(r'^\d+\.\s*', '', l))
                elif actions:
                    actions[-1] += ' ' + re.sub(r'^-\s*', '', l)

    # ── 全局关键风险表（跨模块交叉审阅内或独立章节）──
    risks = []
    risk_h, risk_rows = parse_md_table(text, '### 全局关键风险')
    for row in risk_rows:
        while len(row) < 4: row.append('')
        risks.append({'risk': md_to_html(row[0]), 'severity': strip_bold(row[1]),
                      'scope': md_to_html(row[2]), 'suggestion': md_to_html(row[3])})

    # ── Deep 级深度分析 ──
    deep = parse_deep_analysis(text)

    # ── 从子项目 .md 文件聚合 verdict 数据（当子项目表无 verdict 列时）──
    any_has_verdict = any(sum(p.get('verdicts', {}).values()) > 0 for p in subprojects)
    if not any_has_verdict and subprojects:
        for proj in subprojects:
            # 尝试读取子项目的 .md 文件，从中提取 verdict 统计
            child_md = ''
            if proj.get('htmlFile'):
                child_md = re.sub(r'\.html$', '.md', proj['htmlFile'])
            if not child_md:
                child_md = os.path.join(proj['name'], 'index.md')
            child_md_path = os.path.join(md_dir, child_md)
            if not os.path.exists(child_md_path):
                # 也尝试 name.md
                child_md_path = os.path.join(md_dir, proj['name'] + '.md')
            if os.path.exists(child_md_path):
                try:
                    with open(child_md_path, 'r', encoding='utf-8') as cf:
                        child_text = cf.read()
                    # 从子报告中统计 verdict：搜索 "定论判决：XXX" 模式
                    verdicts = {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0}
                    for vm in re.finditer(r'定论判决[：:]\s*\*{0,2}(核心基石|提纯合并|重塑提取|彻底淘汰)', child_text):
                        v = vm.group(1)
                        if v in verdicts:
                            verdicts[v] += 1
                    # 也检查资产定级表的判决列
                    triage_h_child, triage_rows_child = parse_md_table(child_text, '## 三、资产定级表')
                    for row in triage_rows_child:
                        if len(row) >= 7:
                            v = strip_bold(row[6]).strip('*').strip()
                            if v in verdicts:
                                verdicts[v] += 1
                    if sum(verdicts.values()) > 0:
                        proj['verdicts'] = verdicts
                except Exception:
                    pass

    # ── 检测混合格式：index.md 中是否包含三段式报告 ──
    tree = ''
    modules = []
    triage = []
    if '## 一、资产总览树' in text or '## 一' in text:
        tree = parse_tree(text)
        modules = parse_modules(text)
        triage_h, triage_rows = parse_md_table(text, '## 三、资产定级表')
        for row in triage_rows:
            while len(row) < 7: row.append('')
            triage.append({
                'module': strip_backtick(strip_bold(row[0])),
                'function': md_to_html(row[1]),
                'thirdParty': md_to_html(row[2]),
                'deps': md_to_html(row[3]),
                'activity': md_to_html(row[4]),
                'quality': md_to_html(row[5]),
                'verdict': strip_bold(row[6]).strip('*'),
            })

    # ── 混合格式下：从 triage/modules 向 subprojects 回填 verdict ──
    any_has_verdict2 = any(sum(p.get('verdicts', {}).values()) > 0 for p in subprojects)
    if not any_has_verdict2 and (modules or triage):
        sp_names = {sp['name'] for sp in subprojects}

        # 优先用 triage 表（每行一个模块，名称清晰）
        if triage:
            proj_verdicts = {}  # name → {verdict → count}
            for t in triage:
                v = t.get('verdict', '')
                if v not in ('核心基石', '提纯合并', '重塑提取', '彻底淘汰'):
                    continue
                tname = strip_backtick(strip_bold(t.get('module', ''))).strip()
                # 直接名称匹配
                if tname in sp_names:
                    proj_verdicts.setdefault(tname, {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0})
                    proj_verdicts[tname][v] += 1
                else:
                    # 模糊匹配：triage 模块名包含子项目名或反之
                    for sp_name in sp_names:
                        if sp_name in tname or tname in sp_name:
                            proj_verdicts.setdefault(sp_name, {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0})
                            proj_verdicts[sp_name][v] += 1
                            break
            for sp in subprojects:
                if sp['name'] in proj_verdicts:
                    sp['verdicts'] = proj_verdicts[sp['name']]

        # 补充：用 modules 的 path 匹配未命中的子项目
        if modules:
            for m in modules:
                v = m.get('verdict', '')
                if v not in ('核心基石', '提纯合并', '重塑提取', '彻底淘汰'):
                    continue
                path = m.get('path', '')
                mname = m.get('name', '')
                for sp in subprojects:
                    if sum(sp.get('verdicts', {}).values()) > 0:
                        continue  # 已有 verdict
                    sp_name = sp['name']
                    if sp_name and (sp_name + '/' in path or sp_name + '\\' in path
                                     or path.endswith(sp_name) or path.endswith(sp_name + '/')
                                     or sp_name == mname):
                        sp.setdefault('verdicts', {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0})
                        sp['verdicts'][v] += 1

    # ── 标记哪些子项目有 Deep 分析（递归搜索子目录）──
    has_deep_flag = deep is not None
    DEEP_MARKER = '## Deep 级深度分析'
    for proj in subprojects:
        proj['hasDeep'] = False
        proj['deepCount'] = 0
        # 确定子项目对应的目录
        proj_dir = None
        if proj.get('htmlFile'):
            candidate = os.path.join(md_dir, os.path.dirname(proj['htmlFile']))
            if os.path.isdir(candidate):
                proj_dir = candidate
        if not proj_dir:
            candidate = os.path.join(md_dir, proj['name'])
            if os.path.isdir(candidate):
                proj_dir = candidate
        # 也检查同级 .md 文件（如 base.md）
        flat_md = os.path.join(md_dir, proj['name'] + '.md')
        if os.path.isfile(flat_md):
            try:
                with open(flat_md, 'r', encoding='utf-8') as cf:
                    if DEEP_MARKER in cf.read(80000):
                        proj['hasDeep'] = True
                        proj['deepCount'] = 1
            except Exception:
                pass
        # 递归搜索子目录下所有 .md 文件
        if proj_dir and os.path.isdir(proj_dir):
            deep_count = 0
            for root, dirs, files in os.walk(proj_dir):
                for fname in files:
                    if not fname.endswith('.md'):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as cf:
                            if DEEP_MARKER in cf.read(80000):
                                deep_count += 1
                    except Exception:
                        pass
            if deep_count > 0:
                proj['hasDeep'] = True
                proj['deepCount'] = max(proj.get('deepCount', 0), deep_count)

    # ── 审计总结（复用 parse_summary）──
    summary = parse_summary(text)

    title = os.path.basename(os.path.dirname(md_dir) if os.path.basename(md_dir) == 'scan-output' else md_dir)
    title = (title or target or '源码资产') + ' 总览'

    return {
        'title': title,
        'target': target,
        'date': date,
        'desc': desc,
        'subprojects': subprojects,
        'tree': tree,
        'modules': [{
            'name': m['name'],
            'path': m.get('path', ''),
            'verdict': m.get('verdict', ''),
            'function': m.get('function', ''),
            'coreClasses': m.get('coreClasses', ''),
            'deps': m.get('deps', ''),
            'thirdParty': m.get('thirdParty', ''),
            'codeSize': m.get('codeSize', ''),
            'quality': m.get('quality', ''),
            'activity': m.get('activity', ''),
        } for m in modules],
        'triage': triage,
        'overlaps': overlaps,
        'topology': topology,
        'revisions': revisions,
        'actions': actions,
        'risks': risks,
        'summary': summary,
        'deep': deep,
        'hasDeep': has_deep_flag,
    }


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
    is_index = os.path.basename(args.report).lower() == 'index.md'

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
        output = args.output or os.path.join(report_dir, 'report.html')
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
