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
import re
import json
import argparse
import subprocess
import fnmatch
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ── Default patterns (used when config file is not found) ──
DEFAULT_NOISE_DIRS = {
    ".git", ".svn", ".hg", ".vs", ".idea", ".vscode", "__pycache__",
    "obj", "tmp", "temp",
    "Debug", "Release", "x64", "x86", "ipch",
    "cmake-build-debug", "cmake-build-release",
    ".gradle", "build", "target", ".apt_generated", "generated",
    "DerivedData", "Pods", ".build", "xcuserdata",
    "node_modules", "dist", ".next", ".nuxt", ".output", "coverage",
}

DEFAULT_THIRDPARTY_CONTAINER_NAMES = {
    "3party", "3rd_party", "third_party", "thirdparty", "vendor",
    "external", "deps", "libs", "Pods",
}

DEFAULT_KNOWN_LIBS = [
    "ffmpeg", "libavcodec", "libavdevice", "libavfilter", "libavformat",
    "libavutil", "libswresample", "libswscale",
    "live555", "SDL2", "SDL2-*",
    "boost", "boost_*",
    "librtmp", "libx264", "libx265", "libfaac", "libfaad", "libfdk-aac",
    "libyuv", "libvpx", "libopus",
    "libjpeg", "libpng", "libfreeimage", "libcurl", "libjson", "liblua",
    "openssl", "zlib", "protobuf", "gtest", "googletest",
    "opencv*", "baseclasses", "dshow",
    "asio", "websocketpp", "nlohmann",
]

DEFAULT_SKIP_DUPLICATE_NAMES = {
    "res", "bin", "doc", "docs", "include", "includes", "hooks",
    "info", "logs", "refs", "config", "conf", "html", "plugins",
    "temp", "test", "tests", "objects", "static", "src",
    "libavcodec", "libavdevice", "libavfilter", "libavformat",
    "libavutil", "libswresample", "libswscale",
    "prop-base", "props", "text-base", "tmp", "Properties",
    "detail", "cmake", "m4", "po",
}

# ── Tech stack file extensions ──
TECH_STACKS = {
    "C/C++":        {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"},
    "Java/Android": {".java", ".kt", ".aidl"},
    "iOS (OC/Swift)": {".m", ".mm", ".swift"},
    "Web/JS/TS":    {".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte"},
    "CSS/Style":    {".css", ".scss", ".less"},
}

# ── Build system indicators ──
BUILD_FILE_MAP = {
    "CMakeLists.txt": "CMake",
    "Makefile":       "Make",
    "build.gradle":   "Gradle",
    "build.gradle.kts": "Gradle",
    "pom.xml":        "Maven",
    "Podfile":        "CocoaPods",
    "Package.swift":  "SPM",
    "package.json":   "npm",
}
BUILD_EXT_MAP = {
    ".vcxproj":   "MSVC",
    ".sln":       "VS Solution",
    ".xcodeproj": "Xcode",
    ".pro":       "qmake",
}

# ── All source extensions (union of all tech stacks) ──
SOURCE_EXTS = set()
for _exts in TECH_STACKS.values():
    SOURCE_EXTS.update(_exts)

# ── Version detection patterns ──
VERSION_HEADER_PATTERNS = [
    re.compile(r'#define\s+\w*VERSION\w*\s+"([^"]+)"'),
    re.compile(r'#define\s+\w*VERSION\w*\s+(\d[\d.]+\w*)'),
    re.compile(r'version\s*[:=]\s*["\']?(\d[\d.]+\w*)', re.IGNORECASE),
]
VERSION_DIR_PATTERN = re.compile(r'[-_](\d+(?:\.\d+)+\w*)')


def load_config(config_path=None):
    """Load ignore patterns from JSON config file."""
    if config_path and os.path.isfile(config_path):
        config_file = config_path
    else:
        # Try to find config relative to this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(script_dir, "..", "config", "ignore-patterns.json")

    if os.path.isfile(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            print(f"Loaded config from: {os.path.abspath(config_file)}", file=sys.stderr)

            # Flatten noise_dirs from all language categories
            noise = set()
            noise_section = cfg.get("noise_dirs", {})
            for key, dirs in noise_section.items():
                if key.startswith("_"):
                    continue
                noise.update(dirs)

            # Third-party
            tp = cfg.get("thirdparty_dirs", {})
            container_names = set(tp.get("container_names", []))
            known_libs = tp.get("known_libs", [])

            # Skip duplicate names
            sd = cfg.get("skip_duplicate_names", {})
            skip_names = set(sd.get("names", []))

            return noise, container_names, known_libs, skip_names
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Failed to parse config ({e}), using defaults", file=sys.stderr)

    print("Using built-in default patterns (no config file found)", file=sys.stderr)
    return (DEFAULT_NOISE_DIRS, DEFAULT_THIRDPARTY_CONTAINER_NAMES,
            DEFAULT_KNOWN_LIBS, DEFAULT_SKIP_DUPLICATE_NAMES)


def format_size(size_bytes):
    if size_bytes >= 1 << 30:
        return f"{size_bytes / (1 << 30):.2f} GB"
    if size_bytes >= 1 << 20:
        return f"{size_bytes / (1 << 20):.2f} MB"
    if size_bytes >= 1 << 10:
        return f"{size_bytes / (1 << 10):.2f} KB"
    return f"{size_bytes} B"


def match_known_lib(dirname, known_libs):
    """Check if a directory name matches any known third-party library pattern."""
    lower = dirname.lower()
    for pattern in known_libs:
        if fnmatch.fnmatch(lower, pattern.lower()):
            return pattern
        if fnmatch.fnmatch(dirname, pattern):
            return pattern
    return None


class Scanner:
    def __init__(self, noise_dirs, container_names, known_libs, skip_duplicate_names):
        self.noise_dirs = noise_dirs
        self.container_names = container_names
        self.known_libs = known_libs
        self.skip_duplicate_names = skip_duplicate_names

    def is_noise_path(self, path_parts):
        """Check if any component of the path is a noise directory."""
        return any(p in self.noise_dirs for p in path_parts)

    def is_thirdparty_path(self, path_parts):
        """Check if any component is a known third-party container or lib."""
        for p in path_parts:
            if p in self.container_names:
                return True
            if match_known_lib(p, self.known_libs):
                return True
        return False

    def scan_directory(self, root_path):
        """Walk the directory tree, separating project code / third-party / noise."""
        project_files = []
        thirdparty_files = []
        noise_files = []
        all_dirs = []
        git_repos = []
        thirdparty_found = {}  # dirname -> {paths, size, file_count, version}

        for dirpath, dirnames, filenames in os.walk(root_path):
            rel_dir = os.path.relpath(dirpath, root_path)
            parts = rel_dir.split(os.sep) if rel_dir != "." else []

            all_dirs.append(dirpath)

            # Detect git repos
            if ".git" in dirnames and dirpath != root_path:
                git_repos.append(rel_dir if rel_dir != "." else "(root)")

            in_noise = self.is_noise_path(parts)
            in_thirdparty = self.is_thirdparty_path(parts)

            # Detect third-party libraries at this level
            for d in dirnames:
                lib_match = match_known_lib(d, self.known_libs)
                is_container = d in self.container_names
                if lib_match or is_container:
                    tp_rel = os.path.relpath(os.path.join(dirpath, d), root_path)
                    # Containers use full path as key (each is independent)
                    # Libraries use name as key (group same lib across locations)
                    key = tp_rel if is_container else d.lower()
                    if key not in thirdparty_found:
                        thirdparty_found[key] = {
                            "name": d,
                            "paths": [],
                            "size": 0,
                            "file_count": 0,
                            "version": None,
                            "is_container": is_container,
                        }
                    thirdparty_found[key]["paths"].append(tp_rel)

            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    size = 0
                ext = os.path.splitext(f)[1].lower()
                entry = (fp, size, ext)

                if in_noise:
                    noise_files.append(entry)
                elif in_thirdparty:
                    thirdparty_files.append(entry)
                else:
                    project_files.append(entry)

        # Collect third-party size/count and detect versions
        for key, info in thirdparty_found.items():
            for tp_path in info["paths"]:
                full_path = os.path.join(root_path, tp_path)
                if os.path.isdir(full_path):
                    fc, fs = self._dir_stats(full_path)
                    info["file_count"] += fc
                    info["size"] += fs
                    if not info["version"]:
                        info["version"] = self._detect_version(full_path, info["name"])

        return project_files, thirdparty_files, noise_files, all_dirs, git_repos, thirdparty_found

    def _dir_stats(self, dir_path):
        """Get file count and total size for a directory (quick, no recursion into noise)."""
        count = 0
        total = 0
        for dp, dns, fns in os.walk(dir_path):
            # Skip noise subdirs
            dns[:] = [d for d in dns if d not in self.noise_dirs]
            for f in fns:
                fp = os.path.join(dp, f)
                try:
                    total += os.path.getsize(fp)
                    count += 1
                except OSError:
                    pass
        return count, total

    def _detect_version(self, lib_dir, lib_name):
        """Try to detect version of a third-party library."""
        # 1. Check directory name for version pattern (e.g., SDL2-2.0.14)
        m = VERSION_DIR_PATTERN.search(lib_name)
        if m:
            return m.group(1)

        # 2. Look for common version files
        version_files = ["VERSION", "version.txt", "VERSION.txt", "version",
                         "RELEASE", "package.json", "CMakeLists.txt",
                         "configure.ac", "meson.build"]
        for vf in version_files:
            vfp = os.path.join(lib_dir, vf)
            if os.path.isfile(vfp):
                ver = self._extract_version_from_file(vfp, vf)
                if ver:
                    return ver

        # 3. Scan a few header files for version defines
        try:
            for f in os.listdir(lib_dir):
                if f.endswith((".h", ".hpp")) and "version" in f.lower():
                    ver = self._extract_version_from_header(os.path.join(lib_dir, f))
                    if ver:
                        return ver
        except OSError:
            pass

        return None

    def _extract_version_from_file(self, filepath, filename):
        """Extract version from a known file type."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(4096)  # Only read first 4KB

            if filename == "package.json":
                try:
                    pkg = json.loads(content)
                    return pkg.get("version")
                except json.JSONDecodeError:
                    pass

            if filename in ("CMakeLists.txt", "configure.ac", "meson.build"):
                # Look for project(xxx VERSION x.y.z) or AC_INIT([xxx],[x.y.z])
                m = re.search(r'VERSION\s+(\d[\d.]+)', content, re.IGNORECASE)
                if m:
                    return m.group(1)
                m = re.search(r'AC_INIT\s*\([^,]*,\s*\[?(\d[\d.]+)', content)
                if m:
                    return m.group(1)

            # Plain text version files
            if filename.lower() in ("version", "version.txt", "release"):
                line = content.strip().splitlines()[0] if content.strip() else ""
                m = re.search(r'(\d+(?:\.\d+)+\w*)', line)
                if m:
                    return m.group(1)

        except OSError:
            pass
        return None

    def _extract_version_from_header(self, filepath):
        """Extract version from C/C++ header files."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(8192)
            for pat in VERSION_HEADER_PATTERNS:
                m = pat.search(content)
                if m:
                    return m.group(1)
        except OSError:
            pass
        return None

    def detect_build_systems(self, dir_path, max_depth=3):
        """Detect build systems in a directory up to max_depth."""
        found = set()
        for dirpath, dirnames, filenames in os.walk(dir_path):
            rel = os.path.relpath(dirpath, dir_path)
            if rel != "." and rel.count(os.sep) >= max_depth:
                continue
            if self.is_noise_path(rel.split(os.sep)):
                continue

            for f in filenames:
                if f in BUILD_FILE_MAP:
                    found.add(BUILD_FILE_MAP[f])
                ext = os.path.splitext(f)[1].lower()
                if ext in BUILD_EXT_MAP:
                    found.add(BUILD_EXT_MAP[ext])

            for d in dirnames:
                ext = os.path.splitext(d)[1].lower()
                if ext in BUILD_EXT_MAP:
                    found.add(BUILD_EXT_MAP[ext])

        return found

    def detect_duplicate_dirs(self, root_path):
        """Find directory names appearing in multiple locations (potential code duplication)."""
        dir_locations = defaultdict(list)
        for dirpath, dirnames, _ in os.walk(root_path):
            rel = os.path.relpath(dirpath, root_path)
            parts = rel.split(os.sep) if rel != "." else []
            if self.is_noise_path(parts) or self.is_thirdparty_path(parts):
                continue
            for d in dirnames:
                if (d not in self.noise_dirs
                        and d not in self.container_names
                        and d not in self.skip_duplicate_names
                        and not d.startswith(".")
                        and not match_known_lib(d, self.known_libs)):
                    dir_rel = os.path.relpath(os.path.join(dirpath, d), root_path)
                    dir_locations[d].append(dir_rel)

        return {k: v for k, v in dir_locations.items() if len(v) >= 3}

    def build_tree(self, root_path, max_depth=3):
        """Generate a clean directory tree, marking third-party dirs."""
        lines = [f"{os.path.basename(root_path)}/"]

        def _walk(path, prefix, depth):
            if depth >= max_depth:
                return
            try:
                entries = sorted([
                    e for e in os.listdir(path)
                    if os.path.isdir(os.path.join(path, e)) and e not in self.noise_dirs
                ])
            except PermissionError:
                return

            for i, name in enumerate(entries):
                is_last = (i == len(entries) - 1)
                connector = "└── " if is_last else "├── "

                # Mark third-party dirs
                lib_match = match_known_lib(name, self.known_libs)
                tag = ""
                if name in self.container_names:
                    tag = "  [3rd-party container]"
                elif lib_match:
                    tag = "  [3rd-party lib]"

                lines.append(f"{prefix}{connector}{name}/{tag}")
                next_prefix = f"{prefix}{'    ' if is_last else '│   '}"

                # Don't recurse into third-party dirs
                if not tag:
                    _walk(os.path.join(path, name), next_prefix, depth + 1)

            return

        _walk(root_path, "", 0)
        return lines

    def is_project_aggregate(self, dir_path):
        """Check if a directory is a project aggregate.

        A directory is an aggregate if its root level contains:
        - Any build configuration file (CMakeLists.txt, .sln, build.gradle, etc.), OR
        - 3+ source code files (.c/.cpp/.java/.swift/.ts etc.)
        """
        try:
            entries = os.listdir(dir_path)
        except (PermissionError, OSError):
            return False

        source_count = 0
        for entry in entries:
            full = os.path.join(dir_path, entry)
            if os.path.isfile(full):
                if entry in BUILD_FILE_MAP:
                    return True
                ext = os.path.splitext(entry)[1].lower()
                if ext in BUILD_EXT_MAP:
                    return True
                if ext in SOURCE_EXTS:
                    source_count += 1
                    if source_count >= 3:
                        return True
            elif os.path.isdir(full):
                ext = os.path.splitext(entry)[1].lower()
                if ext in BUILD_EXT_MAP:
                    return True
        return False

    def analyze_hierarchy(self, root_path):
        """Recursively analyze directory hierarchy for project aggregates.

        Returns tree: {name, path, is_aggregate, build_systems, children[]}
        Only includes children that are aggregates or contain aggregate descendants.
        """
        name = os.path.basename(root_path)
        is_agg = self.is_project_aggregate(root_path)
        build_systems = self.detect_build_systems(root_path, max_depth=1) if is_agg else set()

        children = []
        try:
            entries = sorted(os.listdir(root_path))
        except (PermissionError, OSError):
            entries = []

        for entry in entries:
            entry_path = os.path.join(root_path, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry.startswith('.'):
                continue
            if entry in self.noise_dirs:
                continue
            if entry in self.container_names:
                continue
            if match_known_lib(entry, self.known_libs):
                continue

            child = self.analyze_hierarchy(entry_path)
            if child['is_aggregate'] or child['children']:
                children.append(child)

        return {
            'name': name,
            'path': root_path,
            'is_aggregate': is_agg,
            'build_systems': build_systems,
            'children': children,
        }

    def quick_source_stats(self, dir_path):
        """Quick stats: source file count, total source size, tech stacks found.

        Skips noise and third-party directories.
        """
        file_count = 0
        total_size = 0
        stacks_found = set()

        for dirpath, dirnames, filenames in os.walk(dir_path):
            # Skip noise and thirdparty subdirs
            dirnames[:] = [d for d in dirnames
                           if d not in self.noise_dirs
                           and d not in self.container_names
                           and not d.startswith('.')
                           and not match_known_lib(d, self.known_libs)]

            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                for stack_name, exts in TECH_STACKS.items():
                    if ext in exts:
                        fp = os.path.join(dirpath, f)
                        try:
                            sz = os.path.getsize(fp)
                        except OSError:
                            sz = 0
                        file_count += 1
                        total_size += sz
                        stacks_found.add(stack_name)
                        break

        return file_count, total_size, stacks_found


def get_git_info_for_repo(repo_path):
    """Collect git summary for a single repo."""
    try:
        def run_git(args):
            result = subprocess.run(
                ["git"] + args,
                cwd=repo_path, capture_output=True, timeout=15,
                encoding="utf-8", errors="replace"
            )
            return result.stdout.strip() if result.returncode == 0 else ""

        total = run_git(["rev-list", "--count", "HEAD"])
        recent_out = run_git(["log", "--since=1 year ago", "--oneline"])
        recent = len(recent_out.splitlines()) if recent_out else 0
        last = run_git(["log", "-1", "--format=%ai"])
        last_date = last.split(" ")[0] if last else "-"

        return {
            "total": total or "0",
            "recent": recent,
            "last_date": last_date,
        }
    except Exception:
        return None


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
    w("| Project | Build System | Source Files | Source Size | Tech Stack |")
    w("|---------|-------------|-------------|------------|------------|")

    for child in children:
        child_name = child['name']
        child_path = child['path']

        builds = scanner.detect_build_systems(child_path, max_depth=2)
        build_str = ", ".join(sorted(builds)) if builds else "-"

        file_count, total_size, stacks = scanner.quick_source_stats(child_path)
        stack_str = ", ".join(sorted(stacks)) if stacks else "-"

        # Determine link: leaf aggregate → name.md, nested → name/index.md
        child_has_sub = any(c['is_aggregate'] or c['children'] for c in child.get('children', []))
        if child['is_aggregate'] and not child_has_sub:
            link = f"{child_name}.md"
        else:
            link = f"{child_name}/index.md"

        w(f"| [{child_name}]({link}) | {build_str} | {file_count} | {format_size(total_size)} | {stack_str} |")

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
