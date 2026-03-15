"""
parsers.py — repo-scan markdown 报告解析器。

从 markdown 审计报告中提取结构化数据，供 gen_html.py 渲染 HTML。
"""

import json
import os
import re

from i18n import VERDICT_TO_KEY

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
    RED_KW = ['极度过时', '严重冗余', '完全冗余', 'God Object', '彻底淘汰', '严重过时', '重塑提取',
              'Retire', 'Completely Retire', 'Reshape']
    YLW_KW = ['过时', '体积异常', '双副本', '三副本', '重复副本', '硬编码', '已弃用', '应精简',
              '臃肿', '提纯合并', '职责过重', '全局变量', '竞态',
              'Purify & Merge', 'Purify and Merge', 'outdated', 'deprecated']
    GRN_KW = ['核心基石', 'Core', 'Core Cornerstone']
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
    """解析头部元数据（兼容三段式报告格式和 pre-scan 平铺格式）"""
    info = {}
    # 三段式报告格式
    m = re.search(r'\*\*(?:项目|Project)\*\*[：:]\s*`?([^`\n]+)`?', text)
    if m: info['project'] = m.group(1).strip()
    m = re.search(r'\*\*(?:路径|Path)\*\*[：:]\s*`?([^`\n]+)`?', text)
    if m: info['target'] = m.group(1).strip()
    m = re.search(r'\*\*(?:审计日期|Audit Date)\*\*[：:]\s*(\S+)', text)
    if m: info['date'] = m.group(1).strip()
    m = re.search(r'\*\*(?:项目概貌|Overview)\*\*[：:]\s*(.+?)(?:\n|$)', text)
    if m: info['desc'] = m.group(1).strip()
    # pre-scan / L4 子目录格式兼容（Target / Scan Time）
    if 'target' not in info:
        m = re.search(r'\*\*(?:目标|Target)\*\*[：:]\s*`?([^`\n]+)`?', text)
        if m: info['target'] = m.group(1).strip()
    if 'date' not in info:
        m = re.search(r'\*\*(?:扫描时间|Scan Time|Scan Date)\*\*[：:]\s*(\S+)', text)
        if m: info['date'] = m.group(1).strip()
    # 从标题行提取项目名（# Scan Index: xxx）
    if 'project' not in info:
        m = re.search(r'^# (?:Scan Index|审计报告)[：: ]*(.+)', text, re.MULTILINE)
        if m: info['project'] = m.group(1).strip()
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

        mod['path'] = strip_backtick(extract_field(r'\*\*(?:物理落点|Physical Location)\*\*[：:]\s*(.+?)(?:\n-|\n\n|$)'))
        mod['function'] = md_to_html(extract_field(r'\*\*(?:功能全貌矩阵|Capability Matrix)\*\*[：:]\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        # 核心代码模块 — 只提取类名（backtick 包裹），丢弃解释句，用 / 连接
        core_match = re.search(r'\*\*(?:内部核心代码模块|Core Code Modules)\*\*[：:]\s*\n((?:\s+-.+\n?)+)', part)
        core_raw = core_match.group(1) if core_match else \
                   extract_field(r'\*\*(?:内部核心代码模块|Core Code Modules)\*\*[：:]\s*(.+?)(?:\n-\s\*\*|\n\n|$)')
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

        mod['deps'] = md_to_html(extract_field(r'\*\*(?:模块间依赖关系|Dependencies)\*\*[：:]\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        # 三方库引用 — 可能是多行列表
        tp_match = re.search(r'\*\*(?:三方库引用|Third-Party Libs)\*\*[：:]\s*\n((?:\s+-.+\n?)+)', part)
        if tp_match:
            items = re.findall(r'-\s+(.+)', tp_match.group(1))
            mod['thirdParty'] = '<br>'.join(md_to_html(i) for i in items)
        else:
            mod['thirdParty'] = md_to_html(extract_field(r'\*\*(?:三方库引用|Third-Party Libs)\*\*[：:]\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        mod['codeSize'] = md_to_html(extract_field(r'\*\*(?:代码体量|Code Size)\*\*[：:]\s*(.+?)(?:\n-\s\*\*|\n\n|$)'))

        # 质量评估 — 只保留「架构合理性」和「历史包袱」，丢弃「代码活跃度」和「定论判决」
        quality_match = re.search(r'\*\*(?:质量与技术债评估|Quality Assessment)\*\*[：:]\s*\n((?:\s+-.+\n?)+)', part)
        if quality_match:
            items = re.findall(r'-\s+(.+)', quality_match.group(1))
            kept = []
            for item in items:
                # 跳过活跃度行和判决行
                if re.search(r'^(?:代码活跃度|活跃度|Activity|定论判决|Verdict)', item.strip()):
                    continue
                # 「架构合理性」：去掉前缀标签，保留结论
                item = re.sub(r'^(?:架构合理性|Architecture)[：:]\s*', '', item.strip())
                # 「历史包袱」：去掉前缀，改为"技术债:"标签
                if re.match(r'^(?:历史包袱|Legacy)', item):
                    item = re.sub(r'^(?:历史包袱|Legacy)[：:]\s*', '<span style="color:var(--yellow)">Tech Debt:</span> ', item)
                kept.append(md_to_html(item))
            mod['quality'] = '<br>'.join(kept) if kept else ''
        else:
            mod['quality'] = md_to_html(extract_field(r'\*\*(?:质量与技术债评估|Quality Assessment)\*\*[：:]\s*(.+?)(?:\n\n|$)'))

        # 判决 — 支持中英文verdict名
        _verdict_names = '|'.join(re.escape(k) for k in VERDICT_TO_KEY)
        verdict_match = re.search(r'(?:定论判决|Verdict)[：:]\s*\*{0,2}(' + _verdict_names + r')', part)
        if verdict_match:
            mod['verdict'] = strip_bold(verdict_match.group(1)).strip('*').strip()
        else:
            mod['verdict'] = ''

        # 活跃度
        activity_match = re.search(r'(?:代码活跃度|Activity)[：:]\s*(.+?)(?:\n|$)', part)
        if activity_match:
            mod['activity'] = md_to_html(activity_match.group(1).strip())
        else:
            mod['activity'] = ''

        modules.append(mod)
    return modules

def parse_md_table(text, section_header):
    """解析指定章节标题下的 markdown 表格，返回 [dict, ...]"""
    # 先截取本章节文本（到下一个 ## 或 --- 为止）
    # section_header can be a regex pattern (with (?:...) groups) or plain text
    if '(?:' in section_header or '|' in section_header:
        pattern = section_header
    else:
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
    m = re.search(r'## (?:Deep 级深度分析|Deep Analysis)\s*\n(.*?)(?:\n## (?!#)|\Z)', text, re.DOTALL)
    if not m:
        return None
    section = m.group(1)
    deep = {}

    # 精读文件清单
    files_m = re.search(r'### (?:精读文件清单|Files Read)\s*\n((?:(?:\d+\.\s*|[-*]\s*).+\n?)+)', section)
    if files_m:
        deep['files'] = [re.sub(r'^[\d.]+\s*|^[-*]\s*', '', l.strip()) for l in files_m.group(1).strip().split('\n') if l.strip()]

    # 各评估子章节
    for key, zh in [('threadSafety', '线程安全评估'), ('threadSafety', 'Thread Safety'),
                     ('memory', '内存管理评估'), ('memory', 'Memory Management'),
                     ('errorHandling', '错误处理评估'), ('errorHandling', 'Error Handling'),
                     ('apiConsistency', 'API设计一致性'), ('apiConsistency', 'API 设计一致性'),
                     ('apiConsistency', 'API Consistency'),
                     ('extraFindings', 'Deep级补充发现'), ('extraFindings', 'Deep 级补充发现'),
                     ('extraFindings', 'Deep Supplementary Findings'),
                     ('verdictRevision', '判决修正'), ('verdictRevision', 'Verdict Revisions')]:
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

    # ── 平铺格式兼容（L4 子目录 flat .md 格式）──
    # 若上面结构化子章节均未匹配，尝试解析 功能定位/核心类/Bug模式/判决 格式
    if not deep:
        def _extract_flat_section(header_zh, fallback_key):
            """从平铺格式提取一个子章节内容，写入 deep[fallback_key]"""
            pat = r'### ' + re.escape(header_zh) + r'\s*\n(.*?)(?=\n### |\Z)'
            sm = re.search(pat, section, re.DOTALL)
            if not sm:
                return
            raw = sm.group(1).strip()
            items = []
            current = ''
            for line in raw.split('\n'):
                ls = line.strip()
                if re.match(r'^[-*]\s+\*\*|^\d+\.\s+\*\*|^[-*]\s+', ls):
                    if current:
                        items.append(md_to_html(current))
                    current = re.sub(r'^[-*]\s+|^\d+\.\s+', '', ls)
                elif ls and current:
                    current += ' ' + ls
                elif ls:
                    current = ls
            if current:
                items.append(md_to_html(current))
            if items:
                deep[fallback_key] = items

        _extract_flat_section('功能定位', 'extraFindings')
        _extract_flat_section('功能定位与架构', 'extraFindings')
        _extract_flat_section('核心类与接口', 'apiConsistency')
        _extract_flat_section('核心架构发现', 'apiConsistency')
        _extract_flat_section('Bug 模式与技术债', 'threadSafety')
        _extract_flat_section('Bug 模式', 'threadSafety')
        _extract_flat_section('线程安全与内存管理', 'memory')
        # 判决 → verdictRevision
        verdict_pat = r'### 判决\s*\n(.*?)(?=\n### |\Z)'
        vm = re.search(verdict_pat, section, re.DOTALL)
        if vm:
            deep['verdictRevision'] = [md_to_html(vm.group(1).strip())]
        # 判决修正（有些 flat 文件也有此格式）
        vr_pat = r'### 判决修正\s*\n(.*?)(?=\n### |\Z)'
        vrm = re.search(vr_pat, section, re.DOTALL)
        if vrm and 'verdictRevision' not in deep:
            deep['verdictRevision'] = [md_to_html(vrm.group(1).strip())]

    return deep if deep else None


def parse_git_activity(text):
    """解析 Section 7 的 Git 活跃度表格，返回 list of dict"""
    repos = []
    _, rows = parse_md_table(text, '## 7. Git Repositories & Activity')
    for row in rows:
        while len(row) < 4:
            row.append('')
        repos.append({
            'repo': strip_backtick(row[0]),
            'totalCommits': row[1].strip(),
            'recentCommits': row[2].strip(),
            'lastCommit': row[3].strip(),
        })
    return repos


def parse_summary(text):
    """解析审计总结"""
    summary = {}
    # 找到审计总结区域
    m = re.search(r'## (?:审计总结|Audit Summary)\s*\n(.*)', text, re.DOTALL)
    if not m:
        return summary
    section = m.group(1)

    for key, zh in [('profile', '(?:项目整体画像|Project Profile)'),
                    ('risks', '(?:关键风险|Key Risks)'),
                    ('actions', '(?:优先行动建议|Priority Actions)')]:
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
    cpp_m = re.search(r'C/C\+\+.*?(\d+)\s*(?:文件|files)', text)
    java_m = re.search(r'Java.*?(\d+)\s*(?:文件|files)', text)
    ios_m = re.search(r'iOS.*?(\d+)\s*(?:文件|files)', text)
    web_m = re.search(r'Web.*?(\d+)\s*(?:文件|files)', text)

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

def parse_source_dates(text):
    """从 Section 1 Overall Statistics 中提取源码文件修改日期范围"""
    oldest, newest = '', ''
    m = re.search(r'Oldest Source File\s*\|\s*(\d{4}-\d{2}-\d{2})', text)
    if m: oldest = m.group(1)
    m = re.search(r'Newest Source File\s*\|\s*(\d{4}-\d{2}-\d{2})', text)
    if m: newest = m.group(1)
    return oldest, newest

def build_stats(header, modules, text):
    """构建统计卡片"""
    stats = []

    # 代码规模
    m = re.search(r'(\d+)\s*(?:文件|files)\s*/\s*(?:约|~)?\s*(\d+\s*\w+)\s*(?:纯代码|pure code)', text)
    if m:
        stats.append({'label': 'Source Files', 'value': m.group(1), 'color': 'green'})
        stats.append({'label': 'Code Size', 'value': '~' + m.group(2), 'color': 'green'})

    # 源码修改日期范围
    oldest, newest = parse_source_dates(text)
    if newest:
        stats.append({'label': 'Newest Source', 'value': newest, 'color': 'accent'})
    if oldest:
        stats.append({'label': 'Oldest Source', 'value': oldest, 'color': ''})

    # 三方库总体积
    summary_start = max(text.find('## 审计总结'), text.find('## Audit Summary'))
    search_scope = text[summary_start:] if summary_start >= 0 else text
    m = re.search(r'(?:三方库约|third-party ~?)\s*(\d+\s*[KMGT]?B)', search_scope, re.IGNORECASE)
    if not m:
        m = re.search(r'三方库约\s*(\d+\s*\w+)', search_scope)
    if m:
        stats.append({'label': 'Third-Party Size', 'value': '~' + m.group(1), 'color': 'yellow'})

    # 按判决统计（使用标准 key）
    verdicts = {}
    for mod in modules:
        v = mod.get('verdict', '')
        if v:
            vkey = VERDICT_TO_KEY.get(v, v)
            verdicts[vkey] = verdicts.get(vkey, 0) + 1

    stats.append({'label': 'Modules', 'value': str(len(modules)), 'color': 'accent'})
    verdict_colors = {'core': 'green', 'merge': 'yellow', 'rebuild': 'purple', 'retire': 'red'}
    verdict_labels = {'core': '核心基石', 'merge': '提纯合并', 'rebuild': '重塑提取', 'retire': '彻底淘汰'}
    for vkey, count in verdicts.items():
        stats.append({'label': verdict_labels.get(vkey, vkey), 'value': str(count), 'color': verdict_colors.get(vkey, 'accent')})

    return stats

def parse_dual_scan(text):
    """解析 ### 双扫描交叉验证 章节，返回 dict 或 None"""
    m = re.search(r'### (?:双扫描交叉验证|Dual-Scan Cross-Verification)\s*\n(.*?)(?:\n### (?!#)|\n## |\Z)', text, re.DOTALL)
    if not m:
        return None
    section = m.group(1)
    dual = {}

    # 验证概况
    overview = {}
    for key, zh in [('agreeRate', '(?:判决一致率|Agreement Rate)')]:
        om = re.search(re.escape(zh) + r'[：:]\s*(.+?)(?:\n|$)', section)
        if om:
            overview[key] = om.group(1).strip()
    dual['overview'] = overview

    # 判决对比表
    comparisons = []
    comp_m = re.search(r'#### 判决对比\s*\n\|.+\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', section)
    if comp_m:
        for line in comp_m.group(1).strip().split('\n'):
            cells = [clean(c) for c in line.split('|')[1:] if c != '']
            while cells and not cells[-1]:
                cells.pop()
            if len(cells) >= 5:
                comparisons.append({
                    'module': strip_backtick(strip_bold(cells[0])),
                    'agent1': strip_bold(cells[1]),
                    'agent2': strip_bold(cells[2]),
                    'final': strip_bold(cells[3]),
                    'agree': '✓' in cells[4],
                })
    dual['comparisons'] = comparisons

    # 发现对比明细 — 按模块分组
    findings = {}
    detail_m = re.search(r'#### 发现对比明细\s*\n(.*?)(?=\n#### |\Z)', section, re.DOTALL)
    if detail_m:
        detail_text = detail_m.group(1)
        current_mod = ''
        for line in detail_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            mod_m = re.match(r'^#{5}\s+(.+)', line)
            if mod_m:
                current_mod = strip_backtick(mod_m.group(1).strip())
                findings[current_mod] = []
                continue
            if current_mod and re.match(r'^-\s+\[', line):
                # 匹配 [Both] / [Agent-1] / [Agent-2] / [Agent-1:ClaudeCode] / [Agent-2:Codex] 等
                tag_m = re.match(r'^-\s+\[(Both|Agent-1(?::\w+)?|Agent-2(?::\w+)?)\]\s*(.*)', line)
                if tag_m:
                    findings[current_mod].append({
                        'tag': tag_m.group(1),
                        'text': md_to_html(tag_m.group(2)),
                    })
    dual['findings'] = findings

    # 分歧解析
    disputes = []
    disp_m = re.search(r'#### 分歧解析\s*\n(.*?)(?=\n#### |\n### |\n## |\Z)', section, re.DOTALL)
    if disp_m:
        disp_text = disp_m.group(1)
        current_dispute = None
        for line in disp_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            mod_m = re.match(r'^#{5}\s+(.+?)(?:\s*[—\-]+\s*(.*))?$', line)
            if mod_m:
                if current_dispute:
                    disputes.append(current_dispute)
                current_dispute = {
                    'module': strip_backtick(mod_m.group(1).strip()),
                    'subtitle': mod_m.group(2) or '',
                    'lines': [],
                }
                continue
            if current_dispute and line.startswith('-'):
                current_dispute['lines'].append(md_to_html(re.sub(r'^-\s*', '', line)))
        if current_dispute:
            disputes.append(current_dispute)
    dual['disputes'] = disputes

    return dual

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
    dual_scan = parse_dual_scan(text)
    git_activity = parse_git_activity(text)
    stack = estimate_stack(modules, text)
    stats = build_stats(header, modules, text)

    # 资产定级表
    triage_headers, triage_rows = parse_md_table(text, r'## (?:三、资产定级表|III\. Asset Triage|Asset Triage)')
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
    deps_headers, deps_rows = parse_md_table(text, '## (?:附录|Appendix)')
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

    oldest_date, newest_date = parse_source_dates(text)

    report = {
        'title': (header.get('project', '') + ' Audit Report').strip(),
        'target': header.get('target', ''),
        'date': header.get('date', ''),
        'desc': header.get('desc', ''),
        'oldestSource': oldest_date,
        'newestSource': newest_date,
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
        'dualScan': dual_scan,
        'hasDualScan': dual_scan is not None,
        'gitActivity': git_activity,
    }
    return report

# ─── 双扫描解析（index.md 格式）────────────────────────────

def parse_dual_scan_index(text):
    """解析 ## 双扫描交叉验证 章节（index.md 格式），返回 dict 或 None"""
    m = re.search(r'## (?:双扫描交叉验证|Dual-Scan Cross-Verification)[^\n]*\n(.*?)(?:\n## (?!#)|\Z)', text, re.DOTALL)
    if not m:
        return None
    section = m.group(1)
    dual = {}

    # ── Agent 信息 ──
    # 格式: **Agent-1**: Claude Code (Opus 4.6) — Full 级全量扫描
    # 用 " — "（空格+em-dash+空格）或 " - "（空格+连字符+空格）分隔名称和角色
    a1m = re.search(r'\*\*Agent-1\*\*[：:]\s*(.+?)(?:\s+[—–]\s+(.+))?$', section, re.MULTILINE)
    a2m = re.search(r'\*\*Agent-2\*\*[：:]\s*(.+?)(?:\s+[—–]\s+(.+))?$', section, re.MULTILINE)
    dual['agent1'] = {'name': a1m.group(1).strip() if a1m else 'Agent-1',
                      'role': (a1m.group(2) or '').strip() if a1m else ''}
    dual['agent2'] = {'name': a2m.group(1).strip() if a2m else 'Agent-2',
                      'role': (a2m.group(2) or '').strip() if a2m else ''}
    dm = re.search(r'\*\*(?:验证日期|Verification Date)\*\*[：:]\s*(\S+)', section)
    dual['date'] = dm.group(1).strip() if dm else ''
    am = re.search(r'\*\*(?:一致率|Agreement Rate)\*\*[：:]\s*(.+?)(?:\n|$)', section)
    dual['agreeRate'] = am.group(1).strip() if am else ''

    # ── 判决对照表 ──
    comparisons = []
    comp_m = re.search(r'### (?:判决对照表|Verdict Comparison)\s*\n\|.+\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', section)
    if comp_m:
        for line in comp_m.group(1).strip().split('\n'):
            cells = [clean(c) for c in line.split('|')[1:] if c != '']
            while cells and not cells[-1]:
                cells.pop()
            if len(cells) >= 5:
                comparisons.append({
                    'module': strip_backtick(strip_bold(cells[0])),
                    'agent1': strip_bold(cells[1]),
                    'agent2': strip_bold(cells[2]),
                    'final': strip_bold(cells[3]),
                    'agree': '✓' in cells[4],
                })
    dual['comparisons'] = comparisons

    # ── 系统性发现 ──
    sf_m = re.search(r'\*\*(?:系统性发现|Systemic Finding)\*\*[：:]\s*(.+?)(?:\n|$)', section)
    dual['systemicFinding'] = md_to_html(sf_m.group(1).strip()) if sf_m else ''

    # ── 分歧裁决 ──
    disputes = []
    disp_m = re.search(r'#### (?:分歧裁决依据|Dispute Resolution)\s*\n(.*?)(?=\n### |\Z)', section, re.DOTALL)
    if disp_m:
        disp_text = disp_m.group(1)
        current = None
        for line in disp_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            # **[1] module_name → verdict**（source）
            header_m = re.match(r'^\*\*\[(\d+)\]\s+(.+?)\s*→\s*(.+?)\*\*(?:（(.+?)）)?', line)
            if header_m:
                if current:
                    disputes.append(current)
                current = {
                    'num': header_m.group(1),
                    'module': header_m.group(2).strip(),
                    'finalVerdict': header_m.group(3).strip(),
                    'source': header_m.group(4) or '',
                    'findings': [],
                    'reason': '',
                }
                continue
            if not current:
                continue
            # - [Tag] text  或  - 裁决理由：text
            reason_m = re.match(r'^-\s*(?:裁决理由|Reason)[：:]\s*(.*)', line)
            if reason_m:
                current['reason'] = md_to_html(reason_m.group(1))
                continue
            tag_m = re.match(r'^-\s+\[(Both|Agent-1(?::\w+)?|Agent-2(?::\w+)?)\]\s*(.*)', line)
            if tag_m:
                current['findings'].append({
                    'tag': tag_m.group(1),
                    'text': md_to_html(tag_m.group(2)),
                })
        if current:
            disputes.append(current)
    dual['disputes'] = disputes

    # ── 修正后判决汇总 ──
    corrected = []
    corr_m = re.search(r'### (?:修正后判决汇总|Corrected Verdict Summary)\s*\n\|.+\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', section)
    if corr_m:
        for line in corr_m.group(1).strip().split('\n'):
            cells = [clean(c) for c in line.split('|')[1:] if c != '']
            while cells and not cells[-1]:
                cells.pop()
            if len(cells) >= 3:
                corrected.append({
                    'verdict': strip_bold(cells[0]),
                    'count': cells[1].strip(),
                    'modules': cells[2].strip(),
                })
    dual['correctedSummary'] = corrected

    # ── 对比变化 ──
    changes = []
    chg_m = re.search(r'\*\*(?:与单扫描对比变化|Changes from Single Scan)\*\*[：:]?\s*\n((?:-\s+.+\n?)+)', section)
    if chg_m:
        for line in chg_m.group(1).strip().split('\n'):
            line = line.strip()
            if line.startswith('-'):
                changes.append(md_to_html(re.sub(r'^-\s*', '', line)))
    dual['verdictChanges'] = changes

    # ── 总结性注释（blockquote）──
    note_m = re.search(r'>\s*双扫描验证(.+?)(?:\n\n|\n>|\Z)', section, re.DOTALL)
    dual['summaryNote'] = md_to_html(note_m.group(0).replace('> ', '').strip()) if note_m else ''

    # ── Agent-2 独有发现 ──
    unique = []
    uniq_m = re.search(r'### (?:Agent-2 独有发现摘要|Agent-2 Unique Findings)\s*\n(.*?)(?=\n### |\n## |\n---|\Z)', section, re.DOTALL)
    if uniq_m:
        for line in uniq_m.group(1).strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            # 1. **[Agent-2:Codex] module**: text
            fm = re.match(r'^\d+\.\s*\*\*\[(Agent-2(?::\w+)?)\]\s*(.+?)\*\*[：:]\s*(.*)', line)
            if fm:
                unique.append({
                    'tag': fm.group(1),
                    'module': fm.group(2).strip(),
                    'text': md_to_html(fm.group(3)),
                })
    dual['uniqueFindings'] = unique

    return dual


def _parse_agent2_modules(dual_dir):
    """从 .dual-scan/result-batch*.txt 解析 Agent-2 每个模块的原始分析"""
    import glob
    modules = {}
    for fpath in sorted(glob.glob(os.path.join(dual_dir, 'result-batch*.txt'))):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception:
            continue
        if not text.strip():
            continue
        # 按 ### module_name 切分
        for m in re.finditer(r'^### (\S+)\s*\n(.*?)(?=\n### |\Z)', text, re.DOTALL | re.MULTILINE):
            name = m.group(1).strip()
            body = m.group(2)
            verdict_m = re.search(r'\*\*判决\*\*[：:]\s*(.+)', body)
            reason_m = re.search(r'\*\*判决理由\*\*[：:]\s*(.+)', body)
            # 提取关键发现（编号列表）
            findings = []
            findings_m = re.search(r'\*\*关键发现\*\*[：:]\s*\n(.*?)(?:\n-\s+\*\*横向|\Z)', body, re.DOTALL)
            if findings_m:
                raw = findings_m.group(1)
                # 每个编号项可能跨多行
                parts = re.split(r'\n\s+(?=\d+\.\s)', raw)
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    p = re.sub(r'^\d+\.\s*', '', p)
                    # 截断超长发现，保留前 500 字符
                    if len(p) > 500:
                        p = p[:500] + '…'
                    findings.append(md_to_html(p.replace('\n', ' ')))
            # 横向对比
            cross = []
            cross_m = re.search(r'\*\*横向对比\*\*[^：:]*[：:]\s*\n(.*?)(?=\n### |\Z)', body, re.DOTALL)
            if cross_m:
                for line in cross_m.group(1).strip().split('\n'):
                    line = line.strip()
                    if line.startswith('-'):
                        cross.append(md_to_html(re.sub(r'^-\s*', '', line)))
            modules[name] = {
                'verdict': strip_bold(verdict_m.group(1).strip()) if verdict_m else '',
                'verdictReason': md_to_html(reason_m.group(1).strip()) if reason_m else '',
                'findings': findings,
                'crossComparison': cross,
            }
    return modules


def _parse_agent1_modules(md_dir):
    """从 batch*-full-report.md 解析 Agent-1 每个模块的原始分析"""
    import glob
    modules = {}
    for fpath in sorted(glob.glob(os.path.join(md_dir, 'batch*-full-report.md'))):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception:
            continue
        # 按 ### N.N module_name — description 切分
        for m in re.finditer(
                r'^### \d+\.\d+\s+(\S+)\s*(?:—\s*(.+?))?\s*\n(.*?)(?=\n### \d+\.\d+|\n## |\Z)',
                text, re.DOTALL | re.MULTILINE):
            name = m.group(1).strip()
            subtitle = (m.group(2) or '').strip()
            body = m.group(3)
            # 提取结构化字段
            def _field(key):
                fm = re.search(r'\*\*' + re.escape(key) + r'\*\*[：:]\s*(.+?)(?=\n-\s+\*\*|\Z)', body, re.DOTALL)
                if fm:
                    val = fm.group(1).strip()
                    # 截断超长
                    if len(val) > 500:
                        val = val[:500] + '…'
                    return md_to_html(val.replace('\n', ' '))
                return ''

            func = _field('功能全貌矩阵')
            core = _field('内部核心代码模块')
            deps = _field('模块间依赖关系')
            third = _field('三方库引用')
            size = _field('代码体量')

            # 质量评估（多行列表）
            quality_items = []
            qual_m = re.search(r'\*\*质量与技术债评估\*\*[：:]?\s*\n(.*?)(?=\n### |\n## |\Z)', body, re.DOTALL)
            if qual_m:
                for line in qual_m.group(1).strip().split('\n'):
                    line = line.strip()
                    if not line or '定论判决' in line:
                        continue
                    if line.startswith('-'):
                        line = re.sub(r'^-\s*', '', line)
                        if len(line) > 300:
                            line = line[:300] + '…'
                        quality_items.append(md_to_html(line))

            # 判决
            verdict = ''
            _vn_re = '|'.join(re.escape(k) for k in VERDICT_TO_KEY)
            vm = re.search(r'(?:定论判决|Verdict)[：:]\s*\*{0,2}(' + _vn_re + r')', body)
            if vm:
                verdict = vm.group(1)

            modules[name] = {
                'verdict': verdict,
                'subtitle': subtitle,
                'function': func,
                'coreClasses': core,
                'deps': deps,
                'thirdParty': third,
                'codeSize': size,
                'qualityItems': quality_items,
            }
    return modules


def parse_dual_scan_full(text, md_dir):
    """解析双扫描全量数据：index.md 汇总 + Agent-1/Agent-2 原始分析"""
    # 先解析 index.md 中的汇总信息
    dual = parse_dual_scan_index(text)
    if not dual:
        return None

    # 读取两个 Agent 的原始每模块分析
    dual_dir = os.path.join(md_dir, '.dual-scan')
    agent2_data = _parse_agent2_modules(dual_dir) if os.path.isdir(dual_dir) else {}
    agent1_data = _parse_agent1_modules(md_dir)

    # 构建每模块的完整对比数据
    module_details = []
    # 将 disputes 索引化
    dispute_map = {}
    for d in dual.get('disputes', []):
        dispute_map[d['module']] = d

    for comp in dual.get('comparisons', []):
        name = comp['module']
        a1 = agent1_data.get(name, {})
        a2 = agent2_data.get(name, {})
        disp = dispute_map.get(name, {})

        module_details.append({
            'module': name,
            'agent1Verdict': comp.get('agent1', ''),
            'agent2Verdict': comp.get('agent2', ''),
            'finalVerdict': comp.get('final', ''),
            'agree': comp.get('agree', False),
            # Agent-1 详情
            'a1': {
                'subtitle': a1.get('subtitle', ''),
                'function': a1.get('function', ''),
                'coreClasses': a1.get('coreClasses', ''),
                'deps': a1.get('deps', ''),
                'thirdParty': a1.get('thirdParty', ''),
                'codeSize': a1.get('codeSize', ''),
                'qualityItems': a1.get('qualityItems', []),
            },
            # Agent-2 详情
            'a2': {
                'verdictReason': a2.get('verdictReason', ''),
                'findings': a2.get('findings', []),
                'crossComparison': a2.get('crossComparison', []),
            },
            # 分歧裁决
            'dispute': {
                'source': disp.get('source', ''),
                'findings': disp.get('findings', []),
                'reason': disp.get('reason', ''),
            } if disp else None,
        })

    dual['moduleDetails'] = module_details
    return dual


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
                '最后修改': 'lastModified', 'Last Modified': 'lastModified',
                '判决': 'verdict',
            }
            verdicts_sum = {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0,
                           'Core': 0, 'Purify & Merge': 0, 'Reshape': 0, 'Retire': 0}
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
            # 如果表格有直接的 verdict 列（如 "核心基石"/"提纯合并"），转为 verdicts dict
            if proj.get('verdict'):
                v_text = strip_bold(proj['verdict']).strip('*').strip()
                if v_text in verdicts_sum:
                    proj['verdicts'] = {k: 0 for k in verdicts_sum}
                    proj['verdicts'][v_text] = 1
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
    verdict_table_m = re.search(r'## (?:全局资产判决汇总|Global Verdict Summary)[^\n]*\n[^\n]*\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)+)', text)
    if verdict_table_m:
        verdict_map = {}  # verdict_name → list of module names
        for line in verdict_table_m.group(1).strip().split('\n'):
            cells = [clean(c) for c in line.split('|')[1:] if c != '']
            while cells and not cells[-1]:
                cells.pop()
            if not cells:
                continue
            # 支持两种格式:
            # 格式A (3列): 判决 | 模块数 | 模块列表
            # 格式B (6列): name | ... | 总判决 "3/8/5/9"
            if len(cells) >= 6:
                name = strip_backtick(strip_bold(cells[0]))
                if name.startswith('**') or name == '合计':
                    continue
                total_col = cells[-1]
                parts = re.findall(r'(\d+)\+?', total_col)
                if len(parts) >= 4:
                    verdict_map[name] = {
                        '核心基石': int(parts[0]),
                        '提纯合并': int(parts[1]),
                        '重塑提取': int(parts[2]),
                        '彻底淘汰': int(parts[3]),
                    }
            elif len(cells) >= 3:
                # 格式A: | **核心基石** | 13 | remux, output_hls, ... |
                verdict_name = strip_bold(cells[0]).strip('*').strip()
                if verdict_name not in VERDICT_TO_KEY:
                    continue
                modules_text = cells[2] if len(cells) > 2 else ''
                # 提取模块名列表（逗号分隔，可能有 backtick）
                module_names = [strip_backtick(n.strip()) for n in modules_text.split(',') if n.strip() and n.strip() != '—']
                for mname in module_names:
                    verdict_map.setdefault(mname, {'核心基石': 0, '提纯合并': 0, '重塑提取': 0, '彻底淘汰': 0})
                    verdict_map[mname][verdict_name] = 1
        # 将 verdict 数据合并到 subprojects
        for proj in subprojects:
            name = proj.get('name', '')
            if name in verdict_map:
                proj['verdicts'] = verdict_map[name]

    # ── 交叉审阅章节 ──
    overlaps, topology, revisions, actions = [], [], [], []

    cross_m = re.search(r'## (?:跨模块交叉审阅|Cross-Module Review)[^\n]*\n(.*?)(?:\n## (?!#)|\Z)', text, re.DOTALL)
    if cross_m:
        cross_text = cross_m.group(1)

        # 能力重叠表（兼容 3 列和 4 列格式）
        ov_h, ov_rows = parse_md_table(cross_text + '\n## END', '### (?:能力重叠地图|Capability Overlap)')
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
        tp_h, tp_rows = parse_md_table(cross_text + '\n## END', '### (?:依赖拓扑|Dependency Topology)')
        for row in tp_rows:
            while len(row) < 4: row.append('')
            topology.append({'level': row[0], 'module': strip_backtick(row[1]),
                             'dependents': row[2], 'note': md_to_html(row[3])})

        # 修正判决表
        rv_h, rv_rows = parse_md_table(cross_text + '\n## END', '### (?:修正判决|Verdict Revisions)')
        for row in rv_rows:
            while len(row) < 4: row.append('')
            revisions.append({'module': strip_backtick(row[0]),
                              'original': strip_bold(row[1]),
                              'revised': strip_bold(row[2]),
                              'reason': md_to_html(row[3])})

        # 行动优先级（有序列表，兼容多种格式:
        #   1. 直接编号列表
        #   2. #### P0/P1/... 子标题 + 编号列表
        # 提取从 ### 重构行动优先级 到下一个 ### 的全部内容）
        act_m = re.search(r'### (?:重构行动优先级|Refactoring Priority)\s*\n(.*?)(?=\n### |\Z)', cross_text, re.DOTALL)
        if act_m:
            raw_lines = act_m.group(1).strip().split('\n')
            current_prefix = ''
            for l in raw_lines:
                l = l.strip()
                if not l:
                    continue
                # #### P0 — 子标题: 提取为前缀
                sub_m = re.match(r'^#{3,5}\s*(P\d+)\s*[—\-:]+\s*(.*)', l)
                if sub_m:
                    current_prefix = f'[{sub_m.group(1)}] '
                    continue
                if re.match(r'^\d+\.', l):
                    item = re.sub(r'^\d+\.\s*', '', l)
                    actions.append(current_prefix + item)
                elif actions and not l.startswith('#'):
                    actions[-1] += ' ' + re.sub(r'^-\s*', '', l)

    # ── 全局关键风险表（跨模块交叉审阅内或独立章节）──
    risks = []
    risk_h, risk_rows = parse_md_table(text, '### (?:全局关键风险|Global Critical Risks)')
    for row in risk_rows:
        while len(row) < 4: row.append('')
        risks.append({'risk': md_to_html(row[0]), 'severity': strip_bold(row[1]),
                      'scope': md_to_html(row[2]), 'suggestion': md_to_html(row[3])})

    # ── 共性Bug模式表（Deep交叉审阅产出）──
    bugs = []
    if cross_m:
        bug_h, bug_rows = parse_md_table(cross_text + '\n## END', '### (?:共性Bug模式|Common Bug Patterns)')
        for row in bug_rows:
            while len(row) < 4: row.append('')
            bugs.append({'pattern': md_to_html(row[0]), 'modules': md_to_html(row[1]),
                          'severity': strip_bold(row[2]), 'note': md_to_html(row[3])})

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
                    _vn_re = '|'.join(re.escape(k) for k in VERDICT_TO_KEY)
                    verdicts = {k: 0 for k in VERDICT_TO_KEY}
                    for vm in re.finditer(r'(?:定论判决|Verdict)[：:]\s*\*{0,2}(' + _vn_re + r')', child_text):
                        v = vm.group(1)
                        if v in verdicts:
                            verdicts[v] += 1
                    # 也检查资产定级表的判决列
                    triage_h_child, triage_rows_child = parse_md_table(child_text, r'## (?:三、资产定级表|III\. Asset Triage|Asset Triage)')
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
    if '## 一、资产总览树' in text or '## 一' in text or '## I. Asset Tree' in text:
        tree = parse_tree(text)
        modules = parse_modules(text)
        triage_h, triage_rows = parse_md_table(text, r'## (?:三、资产定级表|III\. Asset Triage|Asset Triage)')
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
                if v not in VERDICT_TO_KEY:
                    continue
                tname = strip_backtick(strip_bold(t.get('module', ''))).strip()
                _empty_v = {k: 0 for k in VERDICT_TO_KEY}
                # 直接名称匹配
                if tname in sp_names:
                    proj_verdicts.setdefault(tname, dict(_empty_v))
                    proj_verdicts[tname][v] = proj_verdicts[tname].get(v, 0) + 1
                else:
                    # 模糊匹配：triage 模块名包含子项目名或反之
                    for sp_name in sp_names:
                        if sp_name in tname or tname in sp_name:
                            proj_verdicts.setdefault(sp_name, dict(_empty_v))
                            proj_verdicts[sp_name][v] = proj_verdicts[sp_name].get(v, 0) + 1
                            break
            for sp in subprojects:
                if sp['name'] in proj_verdicts:
                    sp['verdicts'] = proj_verdicts[sp['name']]

        # 补充：用 modules 的 path 匹配未命中的子项目
        if modules:
            _empty_v2 = {k: 0 for k in VERDICT_TO_KEY}
            for m in modules:
                v = m.get('verdict', '')
                if v not in VERDICT_TO_KEY:
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
                        sp.setdefault('verdicts', dict(_empty_v2))
                        sp['verdicts'][v] = sp['verdicts'].get(v, 0) + 1

    # ── 标记哪些子项目有 Deep 分析（递归搜索子目录）──
    has_deep_flag = deep is not None
    DEEP_MARKERS = ['## Deep 级深度分析', '## Deep Analysis']
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
                    _content = cf.read(80000)
                    if any(dm in _content for dm in DEEP_MARKERS):
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
                            _content = cf.read(80000)
                            if any(dm in _content for dm in DEEP_MARKERS):
                                deep_count += 1
                    except Exception:
                        pass
            if deep_count > 0:
                proj['hasDeep'] = True
                proj['deepCount'] = max(proj.get('deepCount', 0), deep_count)

    # ── 双扫描交叉验证 ──
    dual_scan = parse_dual_scan_full(text, md_dir)

    # ── 审计总结（复用 parse_summary）──
    summary = parse_summary(text)

    title = os.path.basename(os.path.dirname(md_dir) if os.path.basename(md_dir) == 'scan-output' else md_dir)
    title = (title or target or 'Source Assets') + ' Overview'

    return {
        'title': title,
        'target': target,
        'date': date,
        'desc': desc,
        'subprojects': subprojects,
        'tree': tree,
        'dualScan': dual_scan,
        'hasDualScan': dual_scan is not None,
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
        'bugs': bugs,
        'summary': summary,
        'deep': deep,
        'hasDeep': has_deep_flag,
    }
