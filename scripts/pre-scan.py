#!/usr/bin/env python3
"""
repo-scan pre-scan script v4
Collects raw data from a source code directory for AI-powered audit.
Cross-platform: Windows / macOS / Linux

Usage:
    python pre-scan.py /path/to/project                          # stdout
    python pre-scan.py /path/to/project -o scan-result.md        # single file
    python pre-scan.py /path/to/project -d ./scan-output         # hierarchical
    python pre-scan.py /path/to/project -c /path/to/config.json  # custom config
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from scanner import (
    Scanner, load_config, format_size, match_known_lib, get_git_info_for_repo,
    TECH_STACKS, BUILD_FILE_MAP, BUILD_EXT_MAP, SOURCE_EXTS,
)


def generate_detail_report(root_path, config_path=None):
    """Generate full 8-chapter detail report for a single project aggregate."""
    root_path = os.path.abspath(root_path)
    noise_dirs, container_names, known_libs, skip_dup = load_config(config_path)
    scanner = Scanner(noise_dirs, container_names, known_libs, skip_dup)

    lines = []
    w = lines.append

    w("# Repo Scan Pre-Scan Report")
    w("")
    w(f"- **Target**: `{root_path}`")
    w(f"- **Scan Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Scan ──
    print("Scanning directory tree...", file=sys.stderr)
    project_files, thirdparty_files, noise_files, all_dirs, git_repos, thirdparty_found = \
        scanner.scan_directory(root_path)

    total_files = len(project_files) + len(thirdparty_files) + len(noise_files)
    total_size = sum(f[1] for f in project_files) + sum(f[1] for f in thirdparty_files) + sum(f[1] for f in noise_files)
    project_size = sum(f[1] for f in project_files)
    tp_size = sum(f[1] for f in thirdparty_files)
    noise_size = sum(f[1] for f in noise_files)

    # ── 1. Overall Statistics ──
    w("")
    w("## 1. Overall Statistics")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Total Files | {total_files} |")
    w(f"| Total Size (raw) | {format_size(total_size)} |")
    w(f"| **Project Source Files** | **{len(project_files)}** |")
    w(f"| **Project Source Size** | **{format_size(project_size)}** |")
    w(f"| Third-Party Files | {len(thirdparty_files)} |")
    w(f"| Third-Party Size | {format_size(tp_size)} |")
    w(f"| Noise Files (build artifacts) | {len(noise_files)} |")
    w(f"| Noise Size (build artifacts) | {format_size(noise_size)} |")
    if total_size > 0:
        w(f"| Project Code Ratio | {project_size / total_size * 100:.1f}% |")

    # Collect source file modification times
    oldest_mt, newest_mt = float('inf'), 0.0
    for fp, sz, ext in project_files:
        if ext in SOURCE_EXTS:
            try:
                mt = os.stat(fp).st_mtime
                if mt > 0:
                    if mt < oldest_mt: oldest_mt = mt
                    if mt > newest_mt: newest_mt = mt
            except OSError:
                pass
    if newest_mt > 0:
        from datetime import datetime as _dt
        w(f"| Oldest Source File | {_dt.fromtimestamp(oldest_mt).strftime('%Y-%m-%d')} |")
        w(f"| Newest Source File | {_dt.fromtimestamp(newest_mt).strftime('%Y-%m-%d')} |")

    # ── 2. Top-Level Directory Breakdown ──
    w("")
    w("## 2. Top-Level Directory Breakdown")
    w("")
    w("| Directory | Project Files | Project Size | Total Size | Build Systems | Notes |")
    w("|-----------|--------------|-------------|------------|---------------|-------|")

    top_dirs = sorted([
        d for d in os.listdir(root_path)
        if os.path.isdir(os.path.join(root_path, d)) and not d.startswith(".")
    ])

    print("Detecting build systems...", file=sys.stderr)
    for d in top_dirs:
        dir_path = os.path.join(root_path, d)

        # Classify this top-level dir
        is_tp_container = d in container_names
        is_tp_lib = match_known_lib(d, known_libs)
        is_noise = d in noise_dirs

        dir_proj = [f for f in project_files if os.path.relpath(f[0], root_path).split(os.sep)[0] == d]
        dir_tp = [f for f in thirdparty_files if os.path.relpath(f[0], root_path).split(os.sep)[0] == d]
        dir_noise = [f for f in noise_files if os.path.relpath(f[0], root_path).split(os.sep)[0] == d]
        dir_all = dir_proj + dir_tp + dir_noise

        proj_count = len(dir_proj)
        proj_sz = sum(f[1] for f in dir_proj)
        total_sz = sum(f[1] for f in dir_all)

        builds = scanner.detect_build_systems(dir_path) if not is_noise else set()
        build_str = ", ".join(sorted(builds)) if builds else "-"

        note = ""
        if is_noise:
            note = "build artifact"
        elif is_tp_container:
            note = "3rd-party container"
        elif is_tp_lib:
            note = "3rd-party lib"

        w(f"| `{d}` | {proj_count} | {format_size(proj_sz)} | {format_size(total_sz)} | {build_str} | {note} |")

    # ── 3. Source File Statistics by Tech Stack (project files only) ──
    w("")
    w("## 3. Source File Statistics by Tech Stack (project files only)")
    w("")
    w("| Tech Stack | File Count | Total Size |")
    w("|------------|------------|------------|")

    for stack_name, exts in TECH_STACKS.items():
        matched = [(fp, sz) for fp, sz, ext in project_files if ext in exts]
        count = len(matched)
        size = sum(s for _, s in matched)
        w(f"| {stack_name} | {count} | {format_size(size)} |")

    # ── 4. Third-Party Dependencies Detected ──
    w("")
    w("## 4. Third-Party Dependencies Detected")
    w("")

    print("Collecting third-party library info...", file=sys.stderr)
    # Separate containers from actual libs
    tp_libs = {k: v for k, v in thirdparty_found.items() if not v["is_container"]}
    tp_containers = {k: v for k, v in thirdparty_found.items() if v["is_container"]}

    if tp_libs:
        w("| Library | Version | Locations | Files | Size |")
        w("|---------|---------|-----------|------:|-----:|")
        for key in sorted(tp_libs.keys()):
            info = tp_libs[key]
            ver = info["version"] or "unknown"
            locs = ", ".join(f"`{p}`" for p in sorted(info["paths"])[:3])
            if len(info["paths"]) > 3:
                locs += f" +{len(info['paths'])-3} more"
            w(f"| {info['name']} | {ver} | {locs} | {info['file_count']} | {format_size(info['size'])} |")
    else:
        w("No known third-party libraries detected.")

    if tp_containers:
        w("")
        w("**Third-party container directories** (may contain multiple libraries):")
        w("")
        for key in sorted(tp_containers.keys()):
            info = tp_containers[key]
            for p in sorted(info["paths"]):
                w(f"- `{p}/` ({info['file_count']} files, {format_size(info['size'])})")

    # ── 5. Suspected Code Duplication ──
    w("")
    w("## 5. Suspected Code Duplication (directories appearing 3+ times)")
    w("")

    print("Detecting duplicate directories...", file=sys.stderr)
    duplicates = scanner.detect_duplicate_dirs(root_path)
    if duplicates:
        sorted_dups = sorted(duplicates.items(), key=lambda x: -len(x[1]))[:20]
        for name, locations in sorted_dups:
            w(f"### `{name}/` ({len(locations)} occurrences)")
            for loc in sorted(locations)[:10]:
                w(f"- `{loc}`")
            if len(locations) > 10:
                w(f"- ... and {len(locations) - 10} more")
            w("")
    else:
        w("No significant directory-level duplication detected.")

    # ── 6. Directory Tree (clean, third-party marked) ──
    w("")
    w("## 6. Directory Tree (noise filtered, third-party marked)")
    w("")
    w("```text")
    print("Building clean directory tree...", file=sys.stderr)
    tree_lines = scanner.build_tree(root_path, max_depth=3)
    lines.extend(tree_lines)
    w("```")

    # ── 7. Git Repositories & Activity ──
    w("")
    w("## 7. Git Repositories & Activity")
    w("")

    root_git = os.path.join(root_path, ".git")
    has_root_git = os.path.exists(root_git)

    all_repos = []
    if has_root_git:
        all_repos.append(("(root)", root_path))
    for repo_rel in git_repos:
        all_repos.append((repo_rel, os.path.join(root_path, repo_rel)))

    if all_repos:
        w(f"Found **{len(all_repos)}** git repositories.")
        w("")
        w("| Repository | Total Commits | Recent (1yr) | Last Commit |")
        w("|-----------|---------------|-------------|-------------|")

        print(f"Analyzing {len(all_repos)} git repos...", file=sys.stderr)
        for rel, full_path in all_repos:
            info = get_git_info_for_repo(full_path)
            if info:
                w(f"| `{rel}` | {info['total']} | {info['recent']} | {info['last_date']} |")
            else:
                w(f"| `{rel}` | - | - | - |")
    else:
        w("No git repositories found.")

    # ── 8. Noise Directory Summary ──
    w("")
    w("## 8. Noise Directory Summary")
    w("")

    noise_by_type = defaultdict(lambda: {"count": 0, "size": 0})
    for dirpath in all_dirs:
        dirname = os.path.basename(dirpath)
        if dirname in noise_dirs:
            try:
                dir_files = list(Path(dirpath).rglob("*"))
                file_count = sum(1 for f in dir_files if f.is_file())
                file_size = sum(f.stat().st_size for f in dir_files if f.is_file())
            except (PermissionError, OSError):
                file_count, file_size = 0, 0
            noise_by_type[dirname]["count"] += file_count
            noise_by_type[dirname]["size"] += file_size

    if noise_by_type:
        w("| Type | Occurrences (files) | Total Size |")
        w("|------|--------------------:|------------|")
        for dtype, info in sorted(noise_by_type.items(), key=lambda x: -x[1]["size"]):
            if info["size"] > 0:
                w(f"| `{dtype}/` | {info['count']} | {format_size(info['size'])} |")
    else:
        w("No noise directories found.")

    return "\n".join(lines)


def generate_index_report(root_path, hierarchy, scanner):
    """Generate lightweight index.md for a container/aggregate with sub-projects."""
    lines = []
    w = lines.append

    name = os.path.basename(root_path)
    children = hierarchy['children']

    w(f"# Scan Index: {name}")
    w("")
    w(f"- **Target**: `{root_path}`")
    w(f"- **Scan Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"- **Sub-projects**: {len(children)}")
    w("")
    w("| Project | Build System | Source Files | Source Size | Tech Stack | Last Modified |")
    w("|---------|-------------|-------------|------------|------------|--------------|")

    for child in children:
        child_name = child['name']
        child_path = child['path']

        builds = scanner.detect_build_systems(child_path, max_depth=2)
        build_str = ", ".join(sorted(builds)) if builds else "-"

        file_count, total_size, stacks, oldest_date, newest_date = scanner.quick_source_stats(child_path)
        stack_str = ", ".join(sorted(stacks)) if stacks else "-"
        time_str = newest_date if newest_date else "-"

        # Determine link: leaf aggregate → name.md, nested → name/index.md
        child_has_sub = any(c['is_aggregate'] or c['children'] for c in child.get('children', []))
        if child['is_aggregate'] and not child_has_sub:
            link = f"{child_name}.md"
        else:
            link = f"{child_name}/index.md"

        w(f"| [{child_name}]({link}) | {build_str} | {file_count} | {format_size(total_size)} | {stack_str} | {time_str} |")

    w("")
    return "\n".join(lines)


def generate_hierarchical_output(root_path, output_dir, config_path=None):
    """Main entry point for hierarchical (directory-based) output.

    Detects project aggregates and generates index + detail reports accordingly.
    """
    root_path = os.path.abspath(root_path)
    noise_dirs, container_names, known_libs, skip_dup = load_config(config_path)
    scanner = Scanner(noise_dirs, container_names, known_libs, skip_dup)

    print("Analyzing project hierarchy...", file=sys.stderr)
    hierarchy = scanner.analyze_hierarchy(root_path)

    os.makedirs(output_dir, exist_ok=True)
    _output_hierarchy(hierarchy, output_dir, scanner, config_path)


def _output_hierarchy(node, output_dir, scanner, config_path):
    """Recursively output hierarchy: index.md for containers, detail .md for leaf aggregates."""
    name = node['name']
    path = node['path']
    has_sub = bool(node['children'])

    if node['is_aggregate'] and not has_sub:
        # Rule 1 & 4: Leaf aggregate → single detail file
        print(f"Generating detail report for: {name}", file=sys.stderr)
        report = generate_detail_report(path, config_path)
        output_file = os.path.join(output_dir, f"{name}.md")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"  -> {output_file}", file=sys.stderr)
        return

    # Rules 2 & 3: Has sub-aggregates → index + recurse
    os.makedirs(output_dir, exist_ok=True)

    print(f"Generating index for: {name}", file=sys.stderr)
    index_content = generate_index_report(path, node, scanner)
    index_file = os.path.join(output_dir, "index.md")
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(index_content)
    print(f"  -> {index_file}", file=sys.stderr)

    # Process each child
    for child in node['children']:
        child_has_sub = any(c['is_aggregate'] or c['children'] for c in child.get('children', []))

        if child['is_aggregate'] and not child_has_sub:
            # Leaf aggregate → detail report in current output_dir
            print(f"Generating detail report for: {child['name']}", file=sys.stderr)
            report = generate_detail_report(child['path'], config_path)
            output_file = os.path.join(output_dir, f"{child['name']}.md")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"  -> {output_file}", file=sys.stderr)
        else:
            # Has sub-aggregates or is container → recurse into subdirectory
            child_output_dir = os.path.join(output_dir, child['name'])
            _output_hierarchy(child, child_output_dir, scanner, config_path)


def main():
    parser = argparse.ArgumentParser(description="repo-scan pre-scan: collect source code metrics")
    parser.add_argument("path", help="Target source code directory")

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", default="",
                              help="Output file path for single-file report (default: stdout)")
    output_group.add_argument("-d", "--output-dir", default="",
                              help="Output directory for hierarchical multi-file output")

    parser.add_argument("-c", "--config", default="", help="Path to ignore-patterns.json config file")
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        print(f"Error: '{args.path}' is not a valid directory", file=sys.stderr)
        sys.exit(1)

    config = args.config if args.config else None

    if args.output_dir:
        # Hierarchical output mode
        generate_hierarchical_output(args.path, args.output_dir, config)
        print(f"\nHierarchical scan complete. Output in: {os.path.abspath(args.output_dir)}", file=sys.stderr)
    else:
        # Single-file output mode (backward compatible)
        report = generate_detail_report(args.path, config)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\nScan result saved to: {args.output}", file=sys.stderr)
        else:
            print(report)


if __name__ == "__main__":
    main()
