# repo-scan

[![Python 3.6+](https://img.shields.io/badge/Python-3.6+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20macOS%20|%20Linux-lightgrey)]()
[![Agent Skill](https://img.shields.io/badge/Agent-Skill-7B61FF)]()

**中文** | [English](README_en.md)

> npm 有 audit，pip 有 safety，Go 有 mod tidy——**C++ 有什么？**
>
> 重构之前，先摸清家底。

![repo-scan banner](images/banner.jpg)

---

## 为什么需要它

你以为你在维护 23 万个文件。跑完 repo-scan 才发现——**只有 8,500 个是自己写的**，其余全是三方库和构建产物。

现有工具都是**单生态纵向工具**，没有一个能横跨技术栈回答"我到底有什么"：

| 工具 | 覆盖范围 | 能做 | 做不到 |
|------|---------|------|--------|
| npm audit / depcheck | JS/TS | 安全漏洞、未使用依赖 | 不管 C++/Java/iOS |
| clang-tidy / cppcheck | C/C++ | 代码风格和 bug | 不统计资产、不检测重复 |
| SonarQube | 多语言 | 代码质量指标 | 需要服务器，不做资产分类 |
| **repo-scan** | **C/C++, Java, iOS, Web** | **资产清查、三方库识别、重复检测、Git 活跃度** | 不做安全扫描、不替代 linter |

**它不是又一个 linter，是重构前的资产普查工具。**

### 谁需要它

- **C/C++ 开发者** — 这个生态没有类似工具。三方库散落在 vendor/ 里，版本要从头文件 `#define` 里人肉找
- **全栈 / 跨平台团队** — Electron (JS + C++ native)、React Native (TS + Java + OC)、混合 monorepo，没有工具给你全局视图
- **架构师 / 技术管理者** — 重构、合并、商业化决策前，需要一份数据驱动的资产底账
- **前端开发者** — 如果你的项目只有一个 package.json，depcheck 够了；但一旦涉及 native 模块或多技术栈，你也需要它

---

## 它能做什么

**repo-scan** 对代码仓库做一次完整的资产清查。Python 3 零依赖，一行命令跑完。

### 核心能力

- **三分类扫描** — 自动将文件归类为 **项目代码** / **三方依赖** / **构建产物**，精确统计占比
- **三方库识别与版本检测** — 自动识别 50+ 已知三方库（FFmpeg、Boost、OpenSSL 等），从 VERSION 文件、头文件 `#define`、`package.json`、`CMakeLists.txt` 等提取版本号
- **四大技术栈** — C/C++、Java/Android、iOS (OC/Swift)、Web (TS/JS/Vue) 全覆盖
- **代码重复检测** — 发现跨目录的同名模块（疑似 copy-paste），自动排除三方库误报
- **Git 活跃度分析** — 自动发现所有子仓库，统计提交历史（哪些模块两年没人动了？）
- **分级报告输出** — 大型 monorepo 自动拆分为 index + 子项目报告，不超出 AI 上下文
- **AI Token 节约** — "文件名推断→关键文件精读→质量抽样"三层策略，不做穷举式逐文件阅读

## 输出格式

三段式审计报告：

| 段落 | 内容 |
|------|------|
| **资产总览树** | 真实物理目录结构，三方库和构建产物已标记 |
| **模块级描述** | 每个模块的功能、核心类名、依赖关系、三方库引用（含版本评估）、代码质量 |
| **资产定级表** | 全局汇总，四级判决：**核心基石** / **提纯合并** / **重塑提取** / **彻底淘汰** |

## 项目结构

```
repo-scan/
├── SKILL.md                       # 技能主文件（Agent 加载入口）
├── reference.md                   # 各技术栈审计维度速查表
├── config/
│   └── ignore-patterns.json       # 可配置的忽略/识别模式
└── scripts/
    └── pre-scan.py                # 预扫描脚本（Python 3，零依赖）
```

## 安装

将本仓库克隆到 Agent 的技能目录：

```bash
# 全局技能目录
git clone https://github.com/haibindev/repo-scan.git ~/.claude/skills/repo-scan

# 或项目级技能目录
git clone https://github.com/haibindev/repo-scan.git .claude/skills/repo-scan
```

## 使用方法

### 作为 Agent 技能

```
/repo-scan /path/to/my-project
```

### 单独运行预扫描脚本

```bash
python scripts/pre-scan.py /path/to/project                    # 输出到终端
python scripts/pre-scan.py /path/to/project -o report.md       # 单文件报告
python scripts/pre-scan.py /path/to/project -d ./scan-output   # 分级目录报告（大型项目推荐）
python scripts/pre-scan.py /path/to/project -c config.json     # 自定义配置
```

### 预扫描输出章节

| # | 章节 | 说明 |
|---|------|------|
| 1 | 总体统计 | 项目代码 / 三方库 / 构建产物 三分类统计 |
| 2 | 顶级目录分解 | 每个顶级目录的文件数、体积、构建系统、分类标记 |
| 3 | 技术栈统计 | 按技术栈（C/C++、Java、iOS、Web）分类统计源码文件 |
| 4 | 三方依赖清单 | 已识别的三方库（库名、版本、位置、体积） |
| 5 | 代码重复检测 | 同名目录出现 3+ 次的疑似代码重复 |
| 6 | 目录树 | 过滤噪声、标记三方库的清洁目录树 |
| 7 | Git 活跃度 | 所有子仓库的提交历史和活跃度 |
| 8 | 噪声汇总 | 构建产物按类型聚合统计 |

## 自定义配置

编辑 `config/ignore-patterns.json` 自定义忽略和识别模式：

```jsonc
{
  "noise_dirs": {
    "common": [".git", ".svn", "obj", "tmp"],       // 通用噪声目录
    "cpp": ["Debug", "Release", "x64", "ipch"],      // C/C++ 构建产物
    "java_android": [".gradle", "build", "target"],   // Java/Android
    "ios": ["DerivedData", "Pods", "xcuserdata"],     // iOS
    "web": ["node_modules", "dist", ".next"]          // Web
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

## 系统要求

- Python 3.6+
- 支持自定义技能的 AI Agent（如 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)）
- Git（可选，用于活跃度分析）

## 星标历史

[![Star History Chart](https://api.star-history.com/svg?repos=haibindev/repo-scan&type=Date)](https://star-history.com/#haibindev/repo-scan&Date)

## 许可证

[MIT](LICENSE)
