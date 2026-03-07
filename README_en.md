# repo-scan

[![Python 3.6+](https://img.shields.io/badge/Python-3.6+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20macOS%20|%20Linux-lightgrey)]()
[![Agent Skill](https://img.shields.io/badge/Agent-Skill-7B61FF)]()

[中文](README.md) | **English**

> An Agent skill for comprehensive source code asset auditing. Know what you have before you refactor.

---

## What It Does

**repo-scan** scans your codebase and generates a detailed asset inventory report, helping teams understand large legacy codebases before making refactoring, consolidation, or commercialization decisions.

### Key Features

- **Three-way classification** — Automatically categorizes files into **project code** / **third-party dependencies** / **build artifacts** with accurate size metrics
- **Third-party detection & versioning** — Auto-identifies 50+ known libraries (FFmpeg, Boost, OpenSSL, etc.) and extracts version info from VERSION files, header `#define`s, `package.json`, `CMakeLists.txt`, etc.
- **Multi-tech-stack** — C/C++, Java/Android, iOS (OC/Swift), Web (TS/JS/Vue) — all four ecosystems covered
- **Code duplication detection** — Finds duplicate directory names across the project, auto-excludes third-party false positives
- **Git activity analysis** — Auto-discovers all sub-repositories with commit history and activity levels
- **Token-efficient AI strategy** — Three-layer analysis: filename inference → key file reading → quality sampling

## Output

Three-section audit report:

| Section | Content |
|---------|---------|
| **Architecture Tree** | Real physical directory structure with third-party and build artifacts marked |
| **Module Descriptions** | Functionality, core class names, dependencies, third-party references (with version assessment), code quality per module |
| **Asset Triage Table** | Global summary with four-level verdict: **Core Asset** / **Extract & Merge** / **Rebuild** / **Deprecate** |

## Project Structure

```
repo-scan/
├── SKILL.md                       # Skill definition (Agent entry point)
├── reference.md                   # Tech stack audit reference tables
├── config/
│   └── ignore-patterns.json       # Configurable ignore/recognition patterns
└── scripts/
    └── pre-scan.py                # Pre-scan script (Python 3, zero deps)
```

## Installation

Clone into your Agent's skills directory:

```bash
# Global skills directory
git clone https://github.com/haibindev/repo-scan.git ~/.claude/skills/repo-scan

# Or project-level
git clone https://github.com/haibindev/repo-scan.git .claude/skills/repo-scan
```

## Usage

### As an Agent Skill

```
/repo-scan /path/to/my-project
```

### Standalone Pre-scan Script

```bash
python scripts/pre-scan.py /path/to/project                    # print to stdout
python scripts/pre-scan.py /path/to/project -o report.md       # save to file
python scripts/pre-scan.py /path/to/project -c config.json     # custom config
```

### Pre-scan Output Sections

| # | Section | Description |
|---|---------|-------------|
| 1 | Overall Statistics | Three-way split: project / third-party / build artifacts |
| 2 | Top-Level Breakdown | File count, size, build system, classification per directory |
| 3 | Tech Stack Stats | Per-stack (C/C++, Java, iOS, Web) source file counts |
| 4 | Third-Party Deps | Detected libraries with name, version, location, size |
| 5 | Code Duplication | Directories appearing 3+ times (potential copy-paste) |
| 6 | Directory Tree | Clean tree with noise filtered and third-party marked |
| 7 | Git Activity | Commit history and activity for all discovered repos |
| 8 | Noise Summary | Build artifact sizes aggregated by type |

## Configuration

Edit `config/ignore-patterns.json` to customize patterns:

```jsonc
{
  "noise_dirs": {
    "common": [".git", ".svn", "obj", "tmp"],
    "cpp": ["Debug", "Release", "x64", "ipch"],
    "java_android": [".gradle", "build", "target"],
    "ios": ["DerivedData", "Pods", "xcuserdata"],
    "web": ["node_modules", "dist", ".next"]
  },
  "thirdparty_dirs": {
    "container_names": ["vendor", "external", "libs"],
    "known_libs": ["ffmpeg", "boost", "openssl", ...]
  },
  "skip_duplicate_names": {
    "names": ["res", "bin", "src", "include", ...]
  }
}
```

## Requirements

- Python 3.6+
- An AI Agent with custom skill support (e.g. [Claude Code](https://docs.anthropic.com/en/docs/claude-code))
- Git (optional, for activity analysis)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=haibindev/repo-scan&type=Date)](https://star-history.com/#haibindev/repo-scan&Date)

## License

[MIT](LICENSE)
