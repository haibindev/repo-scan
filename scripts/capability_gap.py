# -*- coding: utf-8 -*-
"""
capability_gap.py — 增量能力差异检测工具

对比 hbcore 模块与 best candidate 目录，检测三类差异：
1. 新文件（候选有，hbcore 无）→ [MANDATORY-IMPORT]
2. 同名文件 API 差异（.h 符号不同）→ [MANDATORY-EVAL]
3. 同名文件实现差异（.cpp SHA256 不同但符号可能相同）→ [EVAL-IMPL]

对于第 3 类，即使接口相同，也会检测实现层面的关键模式差异：
- std::atomic vs volatile（线程安全升级）
- 智能指针 vs 裸指针（内存安全）
- 错误处理改进
- 新增 #include（依赖变化）
- 关键函数体行数变化

输出 markdown 报告，可直接用于 refactor brief 的 MANDATORY/EVALUATION 清单。

用法：
  py -3 scripts/capability_gap.py                         # 全部模块
  py -3 scripts/capability_gap.py -m base                  # 单模块
  py -3 scripts/capability_gap.py -m base_codec -o report.md  # 指定输出
  py -3 scripts/capability_gap.py --config config.json      # 自定义映射

配置文件格式（JSON）：
{
  "hbcore_root": "D:\\prjs\\hbcore",
  "modules": {
    "base": {
      "hbcore_dir": "base/cpp",
      "candidates": ["D:\\projects\\media_cross\\base", ...]
    }
  }
}
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from datetime import date

# ─── 默认配置 ──────────────────────────────────────────────────────
# hbcore 根目录：优先使用 --hbcore 参数，其次读取环境变量 HBCORE_ROOT
_env_root = os.environ.get("HBCORE_ROOT")
DEFAULT_HBCORE_ROOT = Path(_env_root) if _env_root else None

# 默认输出路径（写到当前工作目录）
DEFAULT_OUTPUT = Path("capability-gap-report.md")

# 模块映射：通过 --config 参数传入 JSON 配置文件（见 config/gap-config-example.json）
# 不在此处硬编码本机路径
DEFAULT_MODULES: dict = {}

SRC_EXTS = {".h", ".hpp", ".cpp", ".c", ".cc", ".cxx"}
HEADER_EXTS = {".h", ".hpp"}
IMPL_EXTS = {".cpp", ".c", ".cc", ".cxx"}

# ─── 工具函数 ──────────────────────────────────────────────────────
def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(path: Path) -> int:
    try:
        return len(path.read_bytes().split(b"\n"))
    except Exception:
        return 0


# ─── C++ 符号提取 ──────────────────────────────────────────────────
_RE_CLASS   = re.compile(r'^\s*(?:class|struct)\s+(\w+)', re.MULTILINE)
_RE_ENUM    = re.compile(r'^\s*enum\s+(?:class\s+)?(\w+)', re.MULTILINE)
_RE_TYPEDEF = re.compile(r'^\s*typedef\s+.+?\s+(\w+)\s*;', re.MULTILINE)
_RE_FUNC    = re.compile(
    r'^[ \t]*(?!if\b|for\b|while\b|switch\b|return\b|else\b|delete\b|new\b|case\b)'
    r'(?:[\w:*&<>,\s]+?)\s+(\w+)\s*\(',
    re.MULTILINE,
)
_RE_DEFINE  = re.compile(r'^\s*#\s*define\s+([A-Z]\w{2,})\b', re.MULTILINE)

_NOISE_WORDS = frozenset({
    "int", "void", "bool", "char", "float", "double", "long", "short",
    "unsigned", "signed", "auto", "const", "static", "virtual", "inline",
    "override", "explicit", "nullptr", "true", "false", "NULL",
    "public", "private", "protected", "return", "sizeof", "alignof",
    "namespace", "using", "template", "typename", "class", "struct", "enum",
    "extern", "volatile", "mutable", "register", "constexpr", "noexcept",
    "this", "throw", "try", "catch", "new", "delete", "if", "else",
    "for", "while", "do", "switch", "case", "break", "continue", "goto",
    "default", "typedef",
})

def extract_symbols(path: Path) -> set:
    """从 C/C++ 文件提取公开符号名集合"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()

    symbols = set()
    for rx in [_RE_CLASS, _RE_ENUM, _RE_TYPEDEF, _RE_FUNC, _RE_DEFINE]:
        for m in rx.finditer(text):
            name = m.group(1)
            if name in _NOISE_WORDS:
                continue
            if name.startswith("_") and name.endswith("_H_"):
                continue
            if len(name) <= 1:
                continue
            symbols.add(name)
    return symbols


# ─── 实现质量模式检测 ───────────────────────────────────────────────
# 检测 .cpp 文件中的关键实现模式差异
QUALITY_PATTERNS = {
    "atomic_usage":    (re.compile(r'\bstd::atomic\b'), "std::atomic 使用"),
    "volatile_flag":   (re.compile(r'\bvolatile\s+bool\b'), "volatile bool（潜在竞态）"),
    "unique_ptr":      (re.compile(r'\bstd::unique_ptr\b'), "unique_ptr"),
    "shared_ptr":      (re.compile(r'\bstd::shared_ptr\b'), "shared_ptr"),
    "raw_new":         (re.compile(r'\bnew\s+\w+[\s\[\(]'), "裸 new"),
    "raw_delete":      (re.compile(r'\bdelete\s'), "裸 delete"),
    "mutex":           (re.compile(r'\bstd::mutex\b|\bstd::lock_guard\b|\bstd::unique_lock\b'), "mutex/lock"),
    "av_hwframe":      (re.compile(r'\bav_hwframe\b|\bhw_frame\b|\bhw_device\b|\bAV_HWDEVICE\b'), "硬件加速帧"),
    "error_check":     (re.compile(r'\bif\s*\(\s*\w+\s*[<!=]=?\s*(?:0|nullptr|NULL)\s*\)'), "错误检查"),
    "swr_free":        (re.compile(r'\bswr_free\b|\bsws_freeContext\b'), "FFmpeg 资源释放"),
    "avcodec_free":    (re.compile(r'\bavcodec_free_context\b|\bavformat_close_input\b'), "codec/format 释放"),
    "thread_create":   (re.compile(r'\bstd::thread\b|\bCreateThread\b|\bpthread_create\b'), "线程创建"),
    "condition_var":   (re.compile(r'\bstd::condition_variable\b|\bcondition_variable\b'), "条件变量"),
}

def detect_impl_patterns(path: Path) -> dict:
    """检测文件中的关键实现模式，返回 {pattern_name: count}"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    counts = {}
    for name, (rx, _desc) in QUALITY_PATTERNS.items():
        c = len(rx.findall(text))
        if c > 0:
            counts[name] = c
    return counts


def detect_include_diff(path_a: Path, path_b: Path) -> tuple:
    """检测两个文件的 #include 差异，返回 (only_in_a, only_in_b)"""
    rx = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE)

    def get_includes(p):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            return set(rx.findall(text))
        except Exception:
            return set()

    inc_a = get_includes(path_a)
    inc_b = get_includes(path_b)
    return sorted(inc_a - inc_b), sorted(inc_b - inc_a)


# ─── 核心比较 ──────────────────────────────────────────────────────
def compare_module(module_name: str, config: dict, hbcore_root: Path) -> dict:
    hbcore_dir = hbcore_root / config["hbcore_dir"]
    if not hbcore_dir.exists():
        return {"error": f"hbcore 目录不存在: {hbcore_dir}", "module": module_name}

    # 收集 hbcore 文件
    hbcore_files = {}   # lowercase name → Path
    hbcore_hashes = {}  # lowercase name → sha256
    hbcore_symbols = {} # lowercase name → set
    hbcore_patterns = {} # lowercase name → pattern counts

    for f in hbcore_dir.iterdir():
        if f.is_file() and f.suffix.lower() in SRC_EXTS:
            key = f.name.lower()
            hbcore_files[key] = f
            hbcore_hashes[key] = file_sha256(f)
            hbcore_symbols[key] = extract_symbols(f)
            if f.suffix.lower() in IMPL_EXTS:
                hbcore_patterns[key] = detect_impl_patterns(f)

    all_hbcore_symbols = set()
    for syms in hbcore_symbols.values():
        all_hbcore_symbols.update(syms)

    results = {
        "module": module_name,
        "hbcore_dir": str(hbcore_dir),
        "hbcore_file_count": len(hbcore_files),
        "candidates": [],
        "new_files": [],
        "diff_files": [],        # API 差异（.h 有新符号）
        "impl_diff_files": [],   # 实现差异（.cpp 内容不同但符号可能相同）
        "new_symbols": [],
    }

    seen_new = set()
    seen_diff = set()

    for cand_path_str in config["candidates"]:
        cand_dir = Path(cand_path_str)
        if not cand_dir.exists():
            results["candidates"].append({"path": cand_path_str, "status": "NOT_FOUND"})
            continue

        cand_info = {
            "path": cand_path_str,
            "status": "OK",
            "file_count": 0,
            "new_files": [],
            "diff_files": [],
            "impl_diff_files": [],
        }

        for f in cand_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in SRC_EXTS:
                continue
            if "副本" in f.name or ".bak" in f.name.lower():
                continue

            cand_info["file_count"] += 1
            key = f.name.lower()
            cand_sha = file_sha256(f)

            if key not in hbcore_files:
                # ── 新文件 ──
                if key not in seen_new:
                    seen_new.add(key)
                    cand_syms = extract_symbols(f)
                    truly_new = cand_syms - all_hbcore_symbols
                    entry = {
                        "filename": f.name,
                        "source": cand_path_str,
                        "full_path": str(f),
                        "line_count": count_lines(f),
                        "symbols_count": len(cand_syms),
                        "new_symbols": sorted(truly_new)[:50],
                        "new_symbols_count": len(truly_new),
                        "is_header": f.suffix.lower() in HEADER_EXTS,
                    }
                    if f.suffix.lower() in IMPL_EXTS:
                        entry["impl_patterns"] = detect_impl_patterns(f)
                    results["new_files"].append(entry)
                    cand_info["new_files"].append(f.name)

            elif cand_sha != hbcore_hashes[key]:
                # ── 同名不同内容 ──
                if key in seen_diff:
                    continue
                seen_diff.add(key)

                cand_syms = extract_symbols(f)
                hb_syms = hbcore_symbols[key]
                new_in_cand = cand_syms - hb_syms
                missing_in_cand = hb_syms - cand_syms

                is_header = f.suffix.lower() in HEADER_EXTS

                # include 差异
                inc_only_hb, inc_only_cand = detect_include_diff(
                    hbcore_files[key], f
                )

                entry = {
                    "filename": f.name,
                    "source": cand_path_str,
                    "full_path": str(f),
                    "hbcore_path": str(hbcore_files[key]),
                    "hbcore_lines": count_lines(hbcore_files[key]),
                    "cand_lines": count_lines(f),
                    "new_symbols": sorted(new_in_cand)[:50],
                    "new_symbols_count": len(new_in_cand),
                    "missing_symbols": sorted(missing_in_cand)[:30],
                    "missing_symbols_count": len(missing_in_cand),
                    "includes_only_in_cand": inc_only_cand,
                    "includes_only_in_hbcore": inc_only_hb,
                    "is_header": is_header,
                }

                if is_header:
                    # 头文件有符号差异 → API 差异
                    if new_in_cand:
                        results["diff_files"].append(entry)
                        cand_info["diff_files"].append(f.name)
                    elif inc_only_cand:
                        # 符号相同但 include 不同 → 轻度差异
                        entry["note"] = "符号相同但 include 不同"
                        results["impl_diff_files"].append(entry)
                        cand_info["impl_diff_files"].append(f.name)
                else:
                    # .cpp 文件 → 实现差异
                    cand_pats = detect_impl_patterns(f)
                    hb_pats = hbcore_patterns.get(key, {})

                    # 计算模式差异
                    pat_diff = {}
                    all_pat_keys = set(cand_pats.keys()) | set(hb_pats.keys())
                    for pk in all_pat_keys:
                        cv = cand_pats.get(pk, 0)
                        hv = hb_pats.get(pk, 0)
                        if cv != hv:
                            desc = QUALITY_PATTERNS[pk][1]
                            pat_diff[pk] = {
                                "desc": desc,
                                "hbcore": hv,
                                "candidate": cv,
                            }

                    entry["pattern_diff"] = pat_diff
                    entry["has_api_diff"] = bool(new_in_cand)

                    if new_in_cand:
                        # .cpp 有新函数实现
                        results["diff_files"].append(entry)
                        cand_info["diff_files"].append(f.name)
                    else:
                        # 仅实现差异
                        results["impl_diff_files"].append(entry)
                        cand_info["impl_diff_files"].append(f.name)

        results["candidates"].append(cand_info)

    # 汇总新符号
    all_new = set()
    for entry in results["new_files"]:
        all_new.update(entry["new_symbols"])
    for entry in results["diff_files"]:
        all_new.update(entry["new_symbols"])
    results["new_symbols"] = sorted(all_new)
    results["new_symbols_count"] = len(all_new)

    return results


# ─── Markdown 报告 ─────────────────────────────────────────────────
def generate_report(all_results: list, output_path: Path, hbcore_root: Path):
    lines = []
    lines.append("# 增量能力差异检测报告")
    lines.append("")
    lines.append(f"- **生成日期**: {date.today()}")
    lines.append(f"- **hbcore**: `{hbcore_root}`")
    lines.append(f"- **模块数**: {len(all_results)}")
    lines.append("")

    # 总览表
    lines.append("## 总览")
    lines.append("")
    lines.append("| 模块 | hbcore 文件 | 新文件 | API 差异 | 实现差异 | 新符号 |")
    lines.append("|------|-----------|--------|---------|---------|-------|")
    for r in all_results:
        if "error" in r:
            lines.append(f"| {r['module']} | ERROR | — | — | — | — |")
        else:
            lines.append(
                f"| {r['module']} "
                f"| {r['hbcore_file_count']} "
                f"| {len(r['new_files'])} "
                f"| {len(r['diff_files'])} "
                f"| {len(r['impl_diff_files'])} "
                f"| {r['new_symbols_count']} |"
            )
    lines.append("")

    # 每模块详细
    for r in all_results:
        if "error" in r:
            lines.append(f"## {r['module']} — ERROR: {r['error']}")
            lines.append("")
            continue

        has_any = r["new_files"] or r["diff_files"] or r["impl_diff_files"]
        tag = "有差异" if has_any else "无差异"
        lines.append(f"## {r['module']} — {tag}")
        lines.append("")
        lines.append(f"- hbcore: `{r['hbcore_dir']}` ({r['hbcore_file_count']} 文件)")
        lines.append("")

        # 候选目录
        lines.append("### 候选目录")
        lines.append("")
        for c in r["candidates"]:
            if c["status"] == "NOT_FOUND":
                lines.append(f"- ~~`{c['path']}`~~ — 未找到")
            else:
                parts = [f"{c['file_count']} 文件"]
                if c.get("new_files"):
                    parts.append(f"{len(c['new_files'])} 新")
                if c.get("diff_files"):
                    parts.append(f"{len(c['diff_files'])} API差异")
                if c.get("impl_diff_files"):
                    parts.append(f"{len(c['impl_diff_files'])} 实现差异")
                lines.append(f"- `{c['path']}` — {', '.join(parts)}")
        lines.append("")

        # ── 新文件 ──
        if r["new_files"]:
            lines.append("### 新文件（候选有，hbcore 无）— [MANDATORY-IMPORT]")
            lines.append("")
            for entry in r["new_files"]:
                tag = "📄" if entry["is_header"] else "⚙️"
                lines.append(f"#### {tag} `{entry['filename']}` ({entry['line_count']} 行)")
                lines.append(f"- 来源: `{entry['full_path']}`")
                if entry["new_symbols"]:
                    lines.append(f"- 新符号 ({entry['new_symbols_count']}): "
                                 f"`{'`, `'.join(entry['new_symbols'][:10])}`"
                                 + (f" ... (+{entry['new_symbols_count']-10})" if entry['new_symbols_count'] > 10 else ""))
                if entry.get("impl_patterns"):
                    pats = entry["impl_patterns"]
                    highlights = []
                    for pk, count in pats.items():
                        desc = QUALITY_PATTERNS[pk][1]
                        highlights.append(f"{desc}×{count}")
                    if highlights:
                        lines.append(f"- 实现特征: {', '.join(highlights)}")
                lines.append("")

        # ── API 差异 ──
        if r["diff_files"]:
            lines.append("### API/符号差异 — [MANDATORY-EVAL]")
            lines.append("")
            for entry in r["diff_files"]:
                tag = "📄" if entry["is_header"] else "⚙️"
                line_info = f"hbcore {entry['hbcore_lines']}行 vs 候选 {entry['cand_lines']}行"
                lines.append(f"#### {tag} `{entry['filename']}` ({line_info})")
                lines.append(f"- hbcore: `{entry['hbcore_path']}`")
                lines.append(f"- 候选:  `{entry['full_path']}`")
                if entry["new_symbols"]:
                    lines.append(f"- **候选新增符号** ({entry['new_symbols_count']}): "
                                 f"`{'`, `'.join(entry['new_symbols'][:10])}`")
                if entry["missing_symbols"]:
                    lines.append(f"- 候选缺少符号 ({entry['missing_symbols_count']}): "
                                 f"`{'`, `'.join(entry['missing_symbols'][:10])}`")
                if entry.get("includes_only_in_cand"):
                    lines.append(f"- 候选新增 include: `{'`, `'.join(entry['includes_only_in_cand'])}`")
                if entry.get("pattern_diff"):
                    lines.append("- 实现模式差异:")
                    for pk, info in entry["pattern_diff"].items():
                        lines.append(f"  - {info['desc']}: hbcore={info['hbcore']} → 候选={info['candidate']}")
                lines.append("")

        # ── 实现差异 ──
        if r["impl_diff_files"]:
            lines.append("### 实现差异（API 相同但内容不同）— [EVAL-IMPL]")
            lines.append("")
            for entry in r["impl_diff_files"]:
                line_info = f"hbcore {entry['hbcore_lines']}行 vs 候选 {entry['cand_lines']}行"
                lines.append(f"#### `{entry['filename']}` ({line_info})")
                lines.append(f"- hbcore: `{entry['hbcore_path']}`")
                lines.append(f"- 候选:  `{entry['full_path']}`")
                if entry.get("note"):
                    lines.append(f"- 备注: {entry['note']}")
                if entry.get("includes_only_in_cand"):
                    lines.append(f"- 候选新增 include: `{'`, `'.join(entry['includes_only_in_cand'])}`")
                if entry.get("includes_only_in_hbcore"):
                    lines.append(f"- hbcore 独有 include: `{'`, `'.join(entry['includes_only_in_hbcore'])}`")
                if entry.get("pattern_diff"):
                    lines.append("- **实现模式差异**:")
                    for pk, info in entry["pattern_diff"].items():
                        direction = "↑ 改进" if _is_improvement(pk, info) else "变化"
                        lines.append(f"  - {info['desc']}: hbcore={info['hbcore']} → 候选={info['candidate']} ({direction})")
                lines.append("")

        if not has_any:
            lines.append("> 无差异。")
            lines.append("")

    # ── MANDATORY 整合清单 ──
    has_gaps = any(
        r.get("new_files") or r.get("diff_files") or r.get("impl_diff_files")
        for r in all_results if "error" not in r
    )
    if has_gaps:
        lines.append("---")
        lines.append("")
        lines.append("## MANDATORY 整合清单（供 codex-brief 使用）")
        lines.append("")
        for r in all_results:
            if "error" in r:
                continue
            if not r["new_files"] and not r["diff_files"] and not r["impl_diff_files"]:
                continue
            lines.append(f"### {r['module']}")
            lines.append("")
            idx = 1
            for entry in r["new_files"]:
                syms = ", ".join(f"`{s}`" for s in entry["new_symbols"][:5])
                lines.append(f"{idx}. **[MANDATORY-IMPORT]** `{entry['filename']}` ← `{entry['source']}`")
                if syms:
                    lines.append(f"   - 关键符号: {syms}")
                idx += 1
            for entry in r["diff_files"]:
                if entry["new_symbols_count"] > 0:
                    syms = ", ".join(f"`{s}`" for s in entry["new_symbols"][:5])
                    lines.append(f"{idx}. **[MANDATORY-EVAL]** `{entry['filename']}` — 候选有 {entry['new_symbols_count']} 个新符号")
                    if syms:
                        lines.append(f"   - 新增: {syms}")
                    idx += 1
            for entry in r["impl_diff_files"]:
                pat_highlights = []
                for pk, info in (entry.get("pattern_diff") or {}).items():
                    if _is_improvement(pk, info):
                        pat_highlights.append(info["desc"])
                if pat_highlights:
                    lines.append(f"{idx}. **[EVAL-IMPL]** `{entry['filename']}` — 实现改进: {', '.join(pat_highlights)}")
                    idx += 1
                elif entry.get("hbcore_lines", 0) != entry.get("cand_lines", 0):
                    diff_pct = abs(entry["cand_lines"] - entry["hbcore_lines"]) / max(entry["hbcore_lines"], 1) * 100
                    if diff_pct > 5:
                        lines.append(f"{idx}. **[EVAL-IMPL]** `{entry['filename']}` — 行数差 {diff_pct:.0f}%")
                        idx += 1
            lines.append("")

    report_text = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")
    return report_text


def _is_improvement(pattern_key: str, info: dict) -> bool:
    """判断模式变化是否是改进方向"""
    hv, cv = info["hbcore"], info["candidate"]
    # 更多 atomic 使用 = 改进
    if pattern_key == "atomic_usage":
        return cv > hv
    # 更少 volatile = 改进
    if pattern_key == "volatile_flag":
        return cv < hv
    # 更多智能指针 = 改进
    if pattern_key in ("unique_ptr", "shared_ptr"):
        return cv > hv
    # 更少裸 new/delete = 改进
    if pattern_key in ("raw_new", "raw_delete"):
        return cv < hv
    # 更多 mutex = 更安全
    if pattern_key == "mutex":
        return cv > hv
    # 更多错误检查 = 改进
    if pattern_key == "error_check":
        return cv > hv
    # 更多 FFmpeg 资源释放 = 改进
    if pattern_key in ("swr_free", "avcodec_free"):
        return cv > hv
    # 硬件加速帧使用 = 新能力
    if pattern_key == "av_hwframe":
        return cv > hv
    return False


# ─── main ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="增量能力差异检测 — 对比 hbcore 与候选目录"
    )
    parser.add_argument("-m", "--module", help="只检测指定模块")
    parser.add_argument("-o", "--output", help="输出报告路径")
    parser.add_argument("--config", help="自定义配置文件 (JSON)")
    parser.add_argument("--hbcore", help="hbcore 根目录（也可设 HBCORE_ROOT 环境变量）",
                        default=str(DEFAULT_HBCORE_ROOT) if DEFAULT_HBCORE_ROOT else None)
    args = parser.parse_args()

    # 确定 hbcore 根目录
    if not args.hbcore:
        print("错误: 请通过 --hbcore 参数或 HBCORE_ROOT 环境变量指定 hbcore 根目录")
        print("示例: py -3 capability_gap.py --hbcore D:/path/to/hbcore --config gap-config.json")
        sys.exit(1)
    hbcore_root = Path(args.hbcore)

    # 加载模块配置
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
        modules = cfg.get("modules", {})
        hbcore_root = Path(cfg.get("hbcore_root", str(hbcore_root)))
    else:
        modules = DEFAULT_MODULES

    if not modules:
        print("错误: 未配置模块映射，请通过 --config 参数指定配置文件")
        print("参考: config/gap-config-example.json")
        sys.exit(1)

    if args.module:
        if args.module not in modules:
            print(f"错误: 模块 '{args.module}' 未配置。可用: {list(modules.keys())}")
            sys.exit(1)
        modules = {args.module: modules[args.module]}

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT

    # 执行检测
    all_results = []
    for name, config in modules.items():
        print(f"\n{'='*60}")
        print(f"检测模块: {name}")
        print(f"{'='*60}")
        result = compare_module(name, config, hbcore_root)
        all_results.append(result)

        if "error" in result:
            print(f"  ❌ {result['error']}")
        else:
            n_new = len(result["new_files"])
            n_diff = len(result["diff_files"])
            n_impl = len(result["impl_diff_files"])
            n_sym = result["new_symbols_count"]
            print(f"  新文件:     {n_new}")
            print(f"  API 差异:   {n_diff}")
            print(f"  实现差异:   {n_impl}")
            print(f"  新符号总数: {n_sym}")

            if result["new_files"]:
                print(f"\n  [MANDATORY-IMPORT] 新文件:")
                for e in result["new_files"]:
                    print(f"    + {e['filename']} ({e['line_count']}行, {e['new_symbols_count']}个新符号)")

            if result["diff_files"]:
                print(f"\n  [MANDATORY-EVAL] API 差异:")
                for e in result["diff_files"]:
                    syms = ", ".join(e["new_symbols"][:5])
                    print(f"    Δ {e['filename']} (+{e['new_symbols_count']}符号: {syms})")

            if result["impl_diff_files"]:
                print(f"\n  [EVAL-IMPL] 实现差异:")
                for e in result["impl_diff_files"]:
                    pats = e.get("pattern_diff", {})
                    highlights = [info["desc"] for pk, info in pats.items() if _is_improvement(pk, info)]
                    extra = f" — 改进: {', '.join(highlights)}" if highlights else ""
                    print(f"    ~ {e['filename']} ({e['hbcore_lines']}→{e['cand_lines']}行{extra})")

    report = generate_report(all_results, output_path, hbcore_root)
    print(f"\n{'='*60}")
    print(f"报告已写入: {output_path}")
    total_issues = sum(
        len(r.get("new_files", [])) + len(r.get("diff_files", [])) + len(r.get("impl_diff_files", []))
        for r in all_results if "error" not in r
    )
    print(f"总差异项: {total_issues}")


if __name__ == "__main__":
    main()
