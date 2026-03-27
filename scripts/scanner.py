"""
Scanner module for repo-scan pre-scan.

Contains the Scanner class, constants, and helper functions for walking
a source tree and classifying files as project / third-party / noise.
"""

import os
import sys
import re
import json
import fnmatch
import subprocess
from collections import defaultdict

# ── Default patterns (used when config file is not found) ──
DEFAULT_NOISE_DIRS = {
    ".git", ".svn", ".hg", ".vs", ".idea", ".vscode", "__pycache__",
    "obj", "tmp", "temp",
    "Debug", "Release", "x64", "x86", "ipch",
    "cmake-build-debug", "cmake-build-release",
    ".gradle", "build", "target", ".apt_generated", "generated",
    "DerivedData", "Pods", ".build", "xcuserdata",
    "TestResults", "artifacts",
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
    "C#/.NET":      {".cs"},
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
    "packages.config": "NuGet",
    "global.json":   ".NET SDK",
    "Directory.Build.props": "MSBuild",
}
BUILD_EXT_MAP = {
    ".vcxproj":   "MSVC",
    ".csproj":    ".NET (C#)",
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
        """Quick stats: source file count, total source size, tech stacks, time range.

        Skips noise and third-party directories.
        Returns: (file_count, total_size, stacks_found, oldest_date, newest_date)
        oldest_date/newest_date are 'YYYY-MM-DD' strings or '' if no files found.
        """
        file_count = 0
        total_size = 0
        stacks_found = set()
        oldest_mtime = float('inf')
        newest_mtime = 0.0

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
                            st = os.stat(fp)
                            sz = st.st_size
                            mt = st.st_mtime
                        except OSError:
                            sz = 0
                            mt = 0
                        file_count += 1
                        total_size += sz
                        stacks_found.add(stack_name)
                        if mt > 0:
                            if mt < oldest_mtime:
                                oldest_mtime = mt
                            if mt > newest_mtime:
                                newest_mtime = mt
                        break

        from datetime import datetime
        oldest_date = datetime.fromtimestamp(oldest_mtime).strftime('%Y-%m-%d') if oldest_mtime < float('inf') else ''
        newest_date = datetime.fromtimestamp(newest_mtime).strftime('%Y-%m-%d') if newest_mtime > 0 else ''

        return file_count, total_size, stacks_found, oldest_date, newest_date


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
