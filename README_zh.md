# repo-scan

[![Python 3.6+](https://img.shields.io/badge/Python-3.6+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20macOS%20|%20Linux-lightgrey)]()
[![Agent Skill](https://img.shields.io/badge/Agent-Skill-7B61FF)]()

[English](README.md) | **中文**

> Agent Skill：架构级跨技术栈源码资产扫描和分析工具。
>
> 每个生态都有自己的依赖管理，但**没有工具能横跨所有技术栈告诉你：你到底有多少自己的代码。** 重构之前，先摸清家底。
>
> 扫描完成后自动生成可交互的本地 HTML 报告，无需联网。多工程 monorepo 支持分级扫描，汇总页点击卡片跳转子项目详情。

![repo-scan banner](images/banner.jpg)

---

## 谁需要它

- **大型项目 / Monorepo 团队** — 项目积累多年，模块众多，需要快速掌握全局资产状况
- **跨平台团队** — Electron、React Native、Flutter 或自研跨平台方案，多技术栈混合，没有工具给你统一视图
- **架构师 / 技术管理者** — 重构、合并、商业化决策前，需要一份数据驱动的资产底账
- **Native 开发者（C/C++、iOS、Android）** — 三方库散落在源码目录里，缺少统一的依赖管理和版本追踪
- **接手遗产代码的人** — 面对陌生的百万行项目，第一步是搞清楚"有什么"而不是"改什么"

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
- **全局交叉审阅** — 所有子项目分析完成后，AI 进行二次阅读，识别跨项目能力重叠、依赖拓扑、修正判决，输出重构优先级
- **可视化 HTML 报告** — 自动生成本地深色主题交互页面；分级模式生成 `index.html` + 各子项目详情页，卡片点击跳转
- **三级分析深度** — `fast` / `standard` / `deep`，平衡速度与深度
- **增量式深度分析** — `deep` 模式基于已有 `standard` 数据，选择性精读高价值模块，检查线程安全、内存管理、错误处理、API 一致性
- **AI Token 节约** — "文件名推断→关键文件精读→质量抽样"三层策略，不做穷举式逐文件阅读

## 分析深度级别

| 级别 | 精读文件数（每模块） | 质量检查 | 适用场景 |
|------|---------------------|---------|---------|
| `fast` | 1-2 个：构建配置 + 最核心头文件 | 仅推断依赖版本 | 超大目录快速摸底（数百模块） |
| `standard` | 2-5 个：头文件 + 入口 + 构建配置 | 完整：依赖、架构、技术债 | 常规审计（默认） |
| `deep` | 5-10 个：增加核心实现、测试、CI | 线程安全、内存、错误处理、API 一致性 | 在 standard 基础上增量深钻 |

**deep 模式是增量式的** — 自动检测已有扫描数据，按判决筛选高价值模块（核心基石 + 提纯合并），追加深度分析。也可手动指定模块：

```
/repo-scan /path/to/project --level deep                          # 自动筛选模块
/repo-scan /path/to/project --level deep --modules base,rtmp_sdk  # 指定模块
```

## 输出格式

三段式 Markdown 审计报告 + 本地 HTML 可视化页面：

| 段落 | 内容 |
|------|------|
| **资产总览树** | 真实物理目录结构，语义压缩，三方库和废弃代码已着色标记 |
| **模块级描述** | 每个模块的功能、核心类名、依赖关系、三方库引用（含版本评估）、代码质量、四级判决 |
| **资产定级表** | 全局汇总，四级判决：**核心基石** / **提纯合并** / **重塑提取** / **彻底淘汰** |
| **跨模块交叉审阅** | 分级模式专有：能力重叠地图、依赖拓扑、修正判决、重构优先级（二次阅读产出） |
| **Deep 深度分析** | 增量模式：逐文件精读、线程安全、内存管理、错误处理、API 一致性（紫色 DEEP 徽章标识） |

### 可视化 HTML 报告

扫描完成后自动生成本地 HTML 页面，无需联网，浏览器直接打开。

![统计概览与资产总览树](images/screenshot-overview.png)

![资产定级表](images/screenshot-triage.png)

**HTML 特性：**
- 统计卡片（子项目数、源码文件数、判决分布）
- 项目卡片上的判决分布条（绿/黄/紫/红）
- 有深度分析的项目显示 **DEEP** 徽章（含数量：`DEEP ×3`）
- 可折叠的总览树、模块描述、定级表、交叉审阅、深度分析章节
- 卡片点击跳转子项目详情页

## 项目结构

```
repo-scan/
├── SKILL.md                       # 技能主文件（Agent 加载入口）
├── reference.md                   # 各技术栈审计维度速查表
├── config/
│   └── ignore-patterns.json       # 可配置的忽略/识别模式
├── scripts/
│   ├── pre-scan.py                # 预扫描脚本（Python 3，零依赖）
│   └── gen_html.py                # HTML 生成脚本（Markdown 报告 → 可视化页面）
└── templates/
    ├── report.html                # 单项目报告模板（深色主题，可交互）
    └── index.html                 # 多项目汇总模板（子项目卡片 + 跨模块分析）
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
/repo-scan /path/to/my-project --level fast
/repo-scan /path/to/my-project --level deep
/repo-scan /path/to/my-project --level deep --modules base,encoder
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

## 系统要求

- Python 3.6+
- 支持自定义技能的 AI Agent（如 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)）
- Git（可选，用于活跃度分析）

## 星标历史

[![Star History Chart](https://api.star-history.com/svg?repos=haibindev/repo-scan&type=Date)](https://star-history.com/#haibindev/repo-scan&Date)

## 许可证

[MIT](LICENSE)
