#!/usr/bin/env python3
"""
i18n.py — repo-scan 多语言支持。

根据系统 locale 自动检测语言（zh/en），提供：
1. detect_lang() — 返回 'zh' 或 'en'
2. get_translations(lang) — 返回 HTML 模板用的 LANG 字典
3. get_console_messages(lang) — 返回 Python 脚本用的控制台消息
"""

import locale
import os
import platform


def detect_lang():
    """检测系统语言，返回 'zh' 或 'en'"""
    # 1. 环境变量优先（允许用户覆盖）
    env_lang = os.environ.get('REPO_SCAN_LANG', '').strip().lower()
    if env_lang in ('zh', 'cn', 'zh_cn', 'zh-cn', 'chinese'):
        return 'zh'
    if env_lang in ('en', 'en_us', 'en-us', 'english'):
        return 'en'

    # 2. Windows: 用 ctypes 获取 UI 语言
    if platform.system() == 'Windows':
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # Chinese: 0x0804 (zh-CN), 0x0404 (zh-TW), 0x0C04 (zh-HK)
            primary = lang_id & 0x3FF
            if primary == 0x04:  # LANG_CHINESE
                return 'zh'
            return 'en'
        except Exception:
            pass

    # 3. POSIX: locale
    try:
        loc = locale.getdefaultlocale()[0] or ''
        if loc.lower().startswith('zh'):
            return 'zh'
    except Exception:
        pass

    # 4. LANG 环境变量
    lang_env = os.environ.get('LANG', '') + os.environ.get('LC_ALL', '')
    if 'zh' in lang_env.lower():
        return 'zh'

    return 'en'


# ═══════════════════════════════════════════════════════════
# HTML 模板用翻译字典
# ═══════════════════════════════════════════════════════════

_LANG_ZH = {
    # ── 通用 ──
    'title_report': '源码资产审计报告',
    'title_index': '源码资产总览',
    'title_dual': '双扫描交叉验证报告',
    'target_path': '目标路径',
    'scan_date': '扫描日期',
    'verify_date': '验证日期',
    'back_to_index': '返回总览',
    'no_data': '暂无数据',

    # ── 判决 ──
    'verdict_core': '核心基石',
    'verdict_merge': '提纯合并',
    'verdict_rebuild': '重塑提取',
    'verdict_retire': '彻底淘汰',

    # ── 统计 ──
    'stat_subprojects': '子项目数',
    'stat_total_files': '总源码文件',
    'stat_modules': '验证模块数',
    'stat_agree': '判决一致',
    'stat_disagree': '判决分歧',
    'stat_agree_rate': '一致率',

    # ── 章节标题 ──
    'sec_subprojects': '子项目一览',
    'sec_tree': '资产总览树',
    'sec_modules': '模块级描述',
    'sec_module_details': '模块详情',
    'sec_triage': '资产定级表',
    'sec_deep': '深度分析',
    'sec_cross': '跨模块交叉审阅',
    'sec_dual': '双扫描交叉验证',
    'sec_summary': '审计总结',
    'sec_tech_stack': '技术栈分布',
    'sec_third_party': '三方依赖总览',
    'sec_unique_findings': 'Agent-2 独有发现',
    'sec_comp_table': '完整对比总表',

    # ── 模块字段 ──
    'field_function': '功能全貌',
    'field_core_classes': '核心代码模块',
    'field_deps': '模块间依赖',
    'field_third_party': '三方库引用',
    'field_code_size': '代码体量',
    'field_quality': '质量评估',
    'field_activity': '活跃度',
    'field_function_matrix': '功能矩阵',
    'field_core_cls': '核心类',
    'field_dep_rel': '依赖关系',
    'field_third_lib': '三方库',

    # ── 定级表列 ──
    'col_module': '模块/目录',
    'col_function': '核心功能',
    'col_third_party': '三方依赖',
    'col_deps': '上下游依赖',
    'col_activity': '活跃度',
    'col_quality': '质量点评',
    'col_verdict': '判决',

    # ── 三方依赖表列 ──
    'col_lib_name': '库名',
    'col_version': '版本',
    'col_location': '位置',
    'col_size': '体积',
    'col_ref_modules': '引用模块',
    'col_usage': '用途',
    'col_assessment': '评估',

    # ── 交叉审阅 ──
    'cross_overlap': '能力重叠地图',
    'cross_topology': '依赖拓扑',
    'cross_revision': '修正判决',
    'cross_actions': '重构行动优先级',
    'cross_bugs': '共性Bug模式（Deep分析发现）',
    'cross_risks': '全局关键风险',

    # ── Deep 分析 ──
    'deep_files': '精读文件清单',
    'deep_thread': '线程安全评估',
    'deep_memory': '内存管理评估',
    'deep_error': '错误处理评估',
    'deep_api': 'API 设计一致性',
    'deep_extra': 'Deep 级补充发现',
    'deep_revised': '判决修正',

    # ── 审计总结 ──
    'summary_profile': '整体画像',
    'summary_risks': '关键风险',
    'summary_actions': '优先行动建议',

    # ── Dual 对比 ──
    'agent1_label': 'Agent-1 · 主扫描方',
    'agent2_label': 'Agent-2 · 独立验证方',
    'systemic_finding': '系统性发现',
    'ai_dispute': 'AI 分歧裁决',

    # ── 筛选 ──
    'filter_all': '全部',
    'filter_disagree': '分歧',
    'filter_agree': '一致',
    'filter_reviewed': '已审阅',
    'filter_unreviewed': '未审阅',
    'search_placeholder': '搜索模块名...',
    'click_detail': '点击查看详细报告',

    # ── 人工审阅 ──
    'human_review': '人工审阅',
    'override_verdict': '覆盖判决',
    'keep_ai': '— 保持 AI 裁决 —',
    'note': '备注',
    'note_placeholder': '人工审阅备注...',
    'proc_ref': '处理参考',
    'proc_ref_placeholder': '综合两个 Agent 的评估，汇总为模块修复/重构的参考信息...',
    'btn_copy_quality': '复制质量评估',
    'btn_copy_full': '复制全部内容',
    'copy_a1_quality': '复制 Agent-1 质量评估内容到处理参考',
    'copy_a2_full': '复制 Agent-2 全部内容到处理参考',
    'toast_copied': '内容已复制到处理参考',
    'mark_reviewed': '标记已审阅',
    'reviewed': '已审阅',
    'pending': '待审',
    'human_override': '人工覆盖',
    'ai_final': 'AI 终判',
    'status': '状态',
    'n_reviewed': '已审阅',
    'n_overrides': '个覆盖',
    'export_btn': '导出决策',
    'import_btn': '导入决策',
    'clear_btn': '清空',
    'import_title': '导入人工决策',
    'import_desc': '选择之前导出的 human-decisions.json 文件，恢复所有审阅状态。',
    'import_drop': '点击选择文件 或 拖拽到此处',
    'cancel': '取消',
    'confirm_clear': '确定清空所有人工审阅记录？此操作不可恢复。',
    'toast_exported': '决策已导出为 human-decisions.json',
    'toast_cleared': '已清空所有审阅记录',
    'toast_override': '覆盖为',
    'toast_restore': '恢复 AI 裁决',
    'toast_mark_reviewed': '已标记审阅',
    'toast_unmark_reviewed': '取消审阅',
    'toast_imported': '已导入 {n} 个模块的决策',
    'import_error': '导入失败',
    'no_modules_field': '无 modules 字段',
    'no_dual_data': '无双扫描数据',
    'open_dual_report': '打开完整双扫描对比报告',
    'dual_desc': '双扫描交叉验证的完整对比报告（含每模块 Agent-1 vs Agent-2 逐项分析）已独立为专用页面。',

    # ── 判决分布 ──
    'verdict_distribution': '模块判决分布',
    'files_unit': '文件',
}

_LANG_EN = {
    # ── Common ──
    'title_report': 'Source Code Asset Audit Report',
    'title_index': 'Source Code Asset Overview',
    'title_dual': 'Dual-Scan Cross-Verification Report',
    'target_path': 'Target Path',
    'scan_date': 'Scan Date',
    'verify_date': 'Verification Date',
    'back_to_index': 'Back to Overview',
    'no_data': 'No data',

    # ── Verdicts ──
    'verdict_core': 'Core',
    'verdict_merge': 'Purify & Merge',
    'verdict_rebuild': 'Reshape',
    'verdict_retire': 'Retire',

    # ── Stats ──
    'stat_subprojects': 'Sub-projects',
    'stat_total_files': 'Source Files',
    'stat_modules': 'Modules Verified',
    'stat_agree': 'Agreed',
    'stat_disagree': 'Disputed',
    'stat_agree_rate': 'Agreement Rate',

    # ── Section titles ──
    'sec_subprojects': 'Sub-projects',
    'sec_tree': 'Asset Tree',
    'sec_modules': 'Module Descriptions',
    'sec_module_details': 'Module Details',
    'sec_triage': 'Asset Triage Table',
    'sec_deep': 'Deep Analysis',
    'sec_cross': 'Cross-Module Review',
    'sec_dual': 'Dual-Scan Cross-Verification',
    'sec_summary': 'Audit Summary',
    'sec_tech_stack': 'Tech Stack Distribution',
    'sec_third_party': 'Third-Party Dependencies',
    'sec_unique_findings': 'Agent-2 Unique Findings',
    'sec_comp_table': 'Full Comparison Table',

    # ── Module fields ──
    'field_function': 'Capabilities',
    'field_core_classes': 'Core Code Modules',
    'field_deps': 'Dependencies',
    'field_third_party': 'Third-Party Libs',
    'field_code_size': 'Code Size',
    'field_quality': 'Quality Assessment',
    'field_activity': 'Activity',
    'field_function_matrix': 'Capability Matrix',
    'field_core_cls': 'Core Classes',
    'field_dep_rel': 'Dependencies',
    'field_third_lib': 'Third-Party',

    # ── Triage table columns ──
    'col_module': 'Module',
    'col_function': 'Core Function',
    'col_third_party': 'Third-Party Deps',
    'col_deps': 'Dependencies',
    'col_activity': 'Activity',
    'col_quality': 'Quality',
    'col_verdict': 'Verdict',

    # ── Third-party table columns ──
    'col_lib_name': 'Library',
    'col_version': 'Version',
    'col_location': 'Location',
    'col_size': 'Size',
    'col_ref_modules': 'Used By',
    'col_usage': 'Usage',
    'col_assessment': 'Assessment',

    # ── Cross review ──
    'cross_overlap': 'Capability Overlap Map',
    'cross_topology': 'Dependency Topology',
    'cross_revision': 'Verdict Revisions',
    'cross_actions': 'Refactoring Priority',
    'cross_bugs': 'Common Bug Patterns (Deep)',
    'cross_risks': 'Global Critical Risks',

    # ── Deep analysis ──
    'deep_files': 'Files Read',
    'deep_thread': 'Thread Safety',
    'deep_memory': 'Memory Management',
    'deep_error': 'Error Handling',
    'deep_api': 'API Consistency',
    'deep_extra': 'Deep Supplementary Findings',
    'deep_revised': 'Verdict Revisions',

    # ── Audit summary ──
    'summary_profile': 'Project Profile',
    'summary_risks': 'Key Risks',
    'summary_actions': 'Priority Actions',

    # ── Dual comparison ──
    'agent1_label': 'Agent-1 · Primary Scanner',
    'agent2_label': 'Agent-2 · Independent Verifier',
    'systemic_finding': 'Systemic Finding',
    'ai_dispute': 'AI Dispute Resolution',

    # ── Filters ──
    'filter_all': 'All',
    'filter_disagree': 'Disputed',
    'filter_agree': 'Agreed',
    'filter_reviewed': 'Reviewed',
    'filter_unreviewed': 'Unreviewed',
    'search_placeholder': 'Search module...',
    'click_detail': 'Click for details',

    # ── Human review ──
    'human_review': 'Human Review',
    'override_verdict': 'Override Verdict',
    'keep_ai': '— Keep AI verdict —',
    'note': 'Notes',
    'note_placeholder': 'Review notes...',
    'proc_ref': 'Processing Reference',
    'proc_ref_placeholder': 'Combine agent findings here as reference for module repair/refactoring...',
    'btn_copy_quality': 'Copy Quality',
    'btn_copy_full': 'Copy Full',
    'copy_a1_quality': 'Copy Agent-1 quality assessment to processing reference',
    'copy_a2_full': 'Copy Agent-2 full content to processing reference',
    'toast_copied': 'content copied to reference',
    'mark_reviewed': 'Mark as Reviewed',
    'reviewed': 'Reviewed',
    'pending': 'Pending',
    'human_override': 'Human Override',
    'ai_final': 'AI Final',
    'status': 'Status',
    'n_reviewed': 'reviewed',
    'n_overrides': 'overridden',
    'export_btn': 'Export Decisions',
    'import_btn': 'Import Decisions',
    'clear_btn': 'Clear',
    'import_title': 'Import Human Decisions',
    'import_desc': 'Select a previously exported human-decisions.json file to restore review states.',
    'import_drop': 'Click to select file or drag here',
    'cancel': 'Cancel',
    'confirm_clear': 'Clear all human review records? This cannot be undone.',
    'toast_exported': 'Decisions exported as human-decisions.json',
    'toast_cleared': 'All review records cleared',
    'toast_override': 'overridden to',
    'toast_restore': 'restored to AI verdict',
    'toast_mark_reviewed': 'marked as reviewed',
    'toast_unmark_reviewed': 'unmarked review',
    'toast_imported': 'Imported decisions for {n} modules',
    'import_error': 'Import failed',
    'no_modules_field': 'No modules field',
    'no_dual_data': 'No dual-scan data',
    'open_dual_report': 'Open Full Dual-Scan Report',
    'dual_desc': 'The full dual-scan comparison report (with per-module Agent-1 vs Agent-2 analysis) is on a separate page.',

    # ── Verdict bar ──
    'verdict_distribution': 'Verdict Distribution',
    'files_unit': 'files',
}


def get_translations(lang=None):
    """返回 HTML 模板用的 LANG 字典"""
    if lang is None:
        lang = detect_lang()
    return _LANG_ZH if lang == 'zh' else _LANG_EN


# ═══════════════════════════════════════════════════════════
# 判决关键词映射（parsers.py 和模板共用）
# ═══════════════════════════════════════════════════════════

VERDICT_NAMES = {
    'zh': ['核心基石', '提纯合并', '重塑提取', '彻底淘汰'],
    'en': ['Core', 'Purify & Merge', 'Reshape', 'Retire'],
}

# 从任意语言的判决名映射到标准 key
VERDICT_TO_KEY = {}
for _lang_code, _names in VERDICT_NAMES.items():
    for _name, _key in zip(_names, ['core', 'merge', 'rebuild', 'retire']):
        VERDICT_TO_KEY[_name] = _key
# 也包含英文全称变体
VERDICT_TO_KEY.update({
    'Core Cornerstone': 'core',
    'Purify & Merge': 'merge',
    'Purify and Merge': 'merge',
    'Reshape & Extract': 'rebuild',
    'Reshape and Extract': 'rebuild',
    'Completely Retire': 'retire',
    'Completely Discard': 'retire',
})
