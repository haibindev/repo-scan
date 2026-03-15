# Full 全量分析模式

> 本文件定义 `--level full` 的完整行为。仅在使用该参数时需要读取。

## 概述

`full` 是最高精度级别，比 `deep` 更进一步：
- **全文件覆盖**：模块内每一个源码文件均被读取和分析，不做抽样
- **横向对比**：跨文件检测功能相似性（不同文件名但实现相似功能的代码）
- **源码配对**：按语言惯例将关联文件成组分析（如 C/C++ 的 .h/.cpp、ObjC 的 .h/.m、Java 的接口/实现类等），不割裂

**适用场景**：
- 整合前的全面摸底（确保不遗漏任何能力）
- 对 deep 分析结果的复核
- 小型模块（<50 个源文件）的完整审计

**限制**：单次 full 分析不超过 **5 个模块**（每个模块需读取全部文件，token 消耗极大）。
超过 5 个模块时报错，要求用户分批指定。

---

## 前置条件

full 是独立的完整分析模式，**不依赖 standard 或 deep 的前置结果**。

- 如果 scan-output 中已有该模块的 standard/deep 报告，可参考但不依赖
- 如果没有任何历史报告，直接从零开始全量分析

---

## 源码配对规则（按语言分组，full 强制执行）

分析时必须将关联文件作为**配对单元**（pair unit）一起读取，避免割裂接口与实现。

### 各语言配对规则

| 语言 | 接口文件 | 实现文件 | 配对名 |
|------|---------|---------|--------|
| **C/C++** | `foo.h` / `foo.hpp` | `foo.cpp` / `foo.cc` / `foo_impl.cpp` | `foo` |
| **C/C++** | `foo.h` | `foo_win.cpp` / `foo_linux.cpp` | `foo`（平台变体） |
| **ObjC** | `Foo.h` | `Foo.m` / `Foo.mm` | `Foo` |
| **Swift** | `FooProtocol.swift` | `Foo.swift` | `Foo`（协议+实现） |
| **Java/Kotlin** | `IFoo.java` / `Foo.kt`(interface) | `FooImpl.java` / `FooImpl.kt` | `Foo`（接口+实现） |
| **Go** | — | 同 package 下所有 `.go` 文件 | package 名 |
| **Rust** | `mod.rs` / `lib.rs` | 同 module 下 `.rs` 文件 | module 名 |
| **Python** | `__init__.py` | 同 package 下 `.py` 文件 | package 名 |
| **TypeScript** | `types.ts` / `index.ts` | 同目录 `.ts`/`.tsx` 文件 | 目录名 |
| **C#** | `IFoo.cs` (interface) | `Foo.cs` | `Foo` |

**通用规则**：
1. **同名优先**：同名的接口文件和实现文件优先配对
2. **前缀/后缀容忍**：`foo.h` + `foo_impl.cpp`、`IFoo.java` + `FooImpl.java` 视为配对
3. **无实现的接口文件**：header-only / 纯接口，单独作为一个分析单元
4. **无接口的实现文件**：可能是入口（main.*）或内部实现，单独标注
5. **包/模块级分组**：Go/Rust/Python 等按 package/module 分组，整个包作为一个分析单元

### 配对分析要求

- 读取配对单元时，**先读接口后读实现**（接口定义契约，实现验证质量）
- 分析输出中，配对单元写在一起：
  ```markdown
  #### foo.h / foo.cpp — 网络传输层（C++）
  - **接口**（foo.h）：class TcpTransport，公开方法 Connect/Send/Recv/Close
  - **实现**（foo.cpp）：基于 IOCP，异步 IO，线程池大小可配
  - **质量**：RAII 资源管理，无裸指针泄漏

  #### UserService.kt（Kotlin）
  - **接口**：interface IUserService，方法 login/logout/getProfile
  - **实现**：UserServiceImpl，基于 Retrofit + Room
  - **质量**：协程使用规范，无回调地狱
  ```
- 横向对比时，配对单元作为整体参与对比（不拆开接口和实现分别对比）

---

## Full 执行流程

```
--level full 触发后：
│
├─ Step F0：验证前置条件
│   ├─ 模块数量 ≤ 5？
│   │   ├─ 是 → 继续
│   │   └─ 否 → 报错，要求分批
│   ├─ 目标模块定位（使用 deep-mode.md 的模块匹配规则）
│   │
│   ├─ 检测已有扫描输出（scan-output/ 下是否有目标模块的 .md 报告）
│   │   │
│   │   ├─ 无已有报告 → 正常执行 F1-F4
│   │   │
│   │   └─ 有已有报告 → 检测系统中是否有其他 AI CLI
│   │       │
│   │       ├─ 有其他 CLI → 提示用户三选一：
│   │       │   ├─ (A) 清理已有报告，当前 CLI 重新执行全量扫描
│   │       │   ├─ (B) 保留已有报告作为 Agent-1 结果，用另一个 CLI 做双重验证
│   │       │   └─ (C) 跳过，直接进入 F6 冒泡和 HTML 生成
│   │       │
│   │       └─ 无其他 CLI → 提示用户二选一：
│   │           ├─ (A) 清理已有报告，重新执行全量扫描
│   │           └─ (C) 跳过，直接进入 F6
│   │
│   └─ 路由：
│       ├─ 选 A → 清理后正常执行 F1-F4，F4 完成后进入 F5 检测双扫描
│       ├─ 选 B → 跳过 F1-F4，直接进入 F5（已有报告 = Agent-1 结果）
│       └─ 选 C → 跳过 F1-F5，直接进入 F6
│
├─ Step F1：全文件枚举与配对
│   ├─ 用 Glob 列出模块目录下所有源码文件（排除三方库和构建产物）
│   ├─ 检测项目语言，按对应配对规则生成配对单元列表
│   └─ 输出文件清单：总文件数、配对单元数、语言分布
│
├─ Step F2：全量精读（按配对单元逐个读取）
│   ├─ 对每个配对单元（或独立文件）：
│   │   ├─ 用 Read 工具读取（先接口后实现）
│   │   ├─ 分析：类/函数清单、依赖关系、质量问题
│   │   └─ 记录该单元的功能摘要（用于 Step F3 横向对比）
│   └─ 所有文件均完整读取和分析，无抽样
│
├─ Step F3：横向对比（Cross-File Comparison）
│   ├─ 基于 F2 的功能摘要，检测以下相似性：
│   │   ├─ 功能重叠：不同文件名但实现相似功能（如两个 JSON 解析器）
│   │   ├─ 接口镜像：不同类但方法签名高度相似（可能是复制演化）
│   │   ├─ 数据结构重复：多处定义相似的 struct/class（如多个 VideoFrame 定义）
│   │   └─ 工具函数重复：散落在不同文件中的相似 helper 函数
│   ├─ 对每组相似文件，输出对比矩阵：
│   │   ├─ 相似度判定（高/中/低）
│   │   ├─ 差异点（各自独有的能力）
│   │   └─ 合并建议（统一到哪个文件、如何合并）
│   └─ 横向对比不限于模块内部——如果指定了多个模块，跨模块对比
│
├─ Step F4：输出 Full 分析报告
│   ├─ 追加到已有 .md 文件末尾（与 deep 追加格式类似）
│   └─ 格式见下方
│
├─ Step F5：跨 CLI 双扫描交叉验证（Dual-Scan Verification，可选）
│   │   触发方式：
│   │   ├─ F0 选 B 直接进入（已有报告 = Agent-1）
│   │   └─ F4 完成后自动检测（新扫描完成 = Agent-1，检测是否有其他 CLI）
│   │
│   ├─ F5a：检测系统中是否安装了其他 AI CLI（where claude / where codex）
│   ├─ F5b：提示用户是否使用另一个 CLI 做验证扫描（F0 选 B 时已确认，跳过）
│   ├─ F5c：构造 prompt 写入临时文件（仅路径，不含分析结论）
│   ├─ F5d：通过 Bash 调用另一个 CLI（只读模式，输出到临时文件）
│   ├─ F5e：读取结果，与自己的分析在内存中对比
│   └─ F5f：追加 ### 双扫描交叉验证 章节到已有报告，清理临时文件
│
├─ Step F6：判决冒泡（复用 deep-mode.md 的冒泡机制）
│   └─ 与 deep 完全相同：逐级更新祖先 index.md
│
└─ Step F7：重新生成 HTML
    └─ 与 deep 完全相同
```

---

## 横向对比（Cross-File Comparison）详细方法

### 第一步：功能指纹提取

对每个配对单元（或独立文件），提取以下"功能指纹"：

```
文件: foo.h / foo.cpp
功能域: 网络传输
核心类: TcpTransport, UdpTransport
关键方法: Connect(), Send(), Recv(), Close(), SetTimeout()
依赖: base::Thread, base::Buffer
模式: Observer 回调, RAII 资源管理
```

### 第二步：相似性矩阵计算

对所有配对单元的功能指纹，两两比较：

| 比较维度 | 权重 | 说明 |
|----------|------|------|
| 功能域匹配 | 40% | 相同功能域（如都是"网络传输"）是最强信号 |
| 方法签名重叠 | 30% | ≥3 个方法名相同或相似（考虑命名变体） |
| 依赖重叠 | 15% | 依赖相同的基础类/三方库 |
| 数据结构相似 | 15% | 使用相似的 struct/enum 定义 |

**相似度阈值**：
- **高（≥70%）**：几乎确定是功能重复，必须标注并建议合并
- **中（40%-70%）**：可能有部分重叠，标注并建议评估
- **低（<40%）**：不标注

### 第三步：对比输出格式

```markdown
### 横向对比发现

#### 对比组 1：视频帧数据结构（高相似度 85%）

| 维度 | desktop_frame.h | video_frame.h | LiveImage.h |
|------|-----------------|---------------|-------------|
| 核心类 | DesktopFrame | VideoFrame | LiveImage |
| 数据格式 | RGBA raw buffer | YUV/RGB | RGB bitmap |
| 内存管理 | SharedDesktopFrame(引用计数) | unique_ptr | 裸指针+手动释放 |
| 独有能力 | 区域标记(DesktopRegion) | — | Alpha 混合 |

**合并建议**：统一到 `VideoFrame`，补入 DesktopRegion 区域标记能力，
  LiveImage 的 Alpha 混合可作为扩展方法。裸指针需替换为智能指针。

#### 对比组 2：...
```

### 命名变体识别

横向对比时，以下命名变体视为"可能是同一概念"：

| 变体类型 | 示例 | 处理 |
|----------|------|------|
| 大小写 | `SendData` vs `send_data` | 视为同一方法 |
| 前缀 | `hbs_send` vs `send` | 视为同一方法 |
| 缩写 | `recv` vs `receive` | 视为同一方法 |
| 同义词 | `destroy` vs `release` vs `close` vs `cleanup` | 视为同一功能位 |
| 类名变体 | `RtmpPublisher` vs `RtmpPush` vs `RtmpSender` | 视为同一功能域 |

---

## Full 分析输出格式（追加到已有 .md 末尾）

```markdown
## Full 级全量分析

### 文件覆盖统计
- 总源码文件数：N
- 配对单元数：M（接口/实现配对）
- 独立文件数：K（无配对的接口或实现文件）
- 语言分布：C++ X 个, Java Y 个, ...

### 全文件清单与分析

#### 1. foo.h / foo.cpp — 网络传输层
- **接口**（foo.h）：class TcpTransport，公开方法 Connect/Send/Recv/Close
- **实现**（foo.cpp）：基于 IOCP，异步 IO
- **质量**：Send() 中 buffer 拷贝可优化为 move

#### 2. bar.h — 常量定义（header-only）
- **内容**：协议常量、错误码枚举
- **发现**：与 base/error_codes.h 有 12 个重复定义

（所有文件逐一列出）

### 横向对比发现

（按上方格式输出所有相似组）

### Full 级补充发现
1. （standard/deep 均未发现的问题）
2. ...

### 判决修正（如有）
- **原判决**: ...
- **修正为**: ...
- **修正理由**: Full 分析发现 ...
```

---

## Step F0 补充：已有报告检测与路由

### 检测逻辑

F0 定位到目标模块后，检查 scan-output/ 下是否已有该模块的 full 级分析报告：

```python
# 检测方式：报告 .md 文件中是否包含 "## Full 级全量分析" 章节
for module in target_modules:
    md_path = f"{scan_output}/{module}.md"  # 或嵌套路径
    if file_exists(md_path) and "## Full 级全量分析" in read(md_path):
        has_existing_report = True
```

### 提示话术

**有其他 CLI 可用时（三选一）：**

```
检测到目标模块已有 Full 级扫描报告（来自之前的分析）。
同时检测到系统中安装了 {other_cli_name}。请选择：

  (A) 清理已有报告，由当前 {self_cli_name} 重新执行全量扫描
  (B) 保留已有报告，使用 {other_cli_name} 做独立验证 → 双扫描交叉对比
  (C) 跳过扫描，直接用已有报告生成 HTML

推荐选 B — 已有报告 + 另一个 AI 的独立验证 = 最高可信度
```

**无其他 CLI 可用时（二选一）：**

```
检测到目标模块已有 Full 级扫描报告（来自之前的分析）。请选择：

  (A) 清理已有报告，重新执行全量扫描
  (C) 跳过扫描，直接用已有报告生成 HTML
```

### 路由

| 选项 | 执行路径 | Agent-1 结果来源 |
|------|---------|-----------------|
| A | 清理 → F1-F4 → F5（可选） → F6-F7 | 当前 CLI 新扫描 |
| B | 跳过 F1-F4 → 直接 F5 | 已有报告 |
| C | 跳过 F1-F5 → 直接 F6-F7 | 已有报告 |

**选项 B 的特殊处理**：
- 从已有报告中提取判决和关键发现，作为 Agent-1 的结果
- Agent-1 的身份标注为**生成该报告的 CLI**（如果报告中有标注），否则标注为"先前分析"
- 进入 F5 时 F5b 已确认，直接从 F5c 开始

---

## Step F5：跨 CLI 双扫描交叉验证（Dual-Scan Verification）

> 此功能仅在 `--level full` 模式下可用，不影响 fast/standard/deep 模式。

### 核心思路

用**不同的 AI CLI 工具**对同一源码进行独立分析，交叉验证以提高可信度。

**两种触发路径**：
1. **F0 选 B**：已有报告 + 另一个 CLI 验证（最省 token，推荐）
2. **F4 完成后**：刚做完新扫描，检测到有另一个 CLI，追加验证

### 架构说明

```
┌─────────────────────────────────────────────────────────────┐
│  当前 CLI（Agent-1，例如 Claude Code）                        │
│                                                             │
│  路径 1：F1-F4 完成 → 报告写入 scan-output/*.md               │
│  路径 2：F0 选 B → 已有报告即 Agent-1 结果                    │
│       │                                                     │
│       ▼                                                     │
│  F5a: 检测系统中是否安装了其他 AI CLI                          │
│       │  where claude / where codex                         │
│       │  排除自己 → 找到另一个 CLI                            │
│       │                                                     │
│       ▼                                                     │
│  F5b: 提示用户（F0 选 B 时已确认，跳过此步）                   │
│       │  "检测到系统安装了 Codex CLI，是否用它做双重扫描？"     │
│       │                                                     │
│       ▼ (用户确认)                                           │
│  F5c: 构造 prompt → 写入临时文件                              │
│       │  /tmp/dual-scan-prompt.txt                           │
│       │  ⚠ 不含 Agent-1 的分析结论                           │
│       │                                                     │
│       ▼                                                     │
│  F5d: 通过 Bash 调用另一个 CLI                                │
│       │                                                     │
│       │  ┌─────────────────────────────────────────┐        │
│       │  │ codex exec - < prompt.txt               │        │
│       │  │   -s read-only                          │        │
│       │  │   -o /tmp/dual-scan-result.txt          │        │
│       │  │                                         │        │
│       │  │ 或                                      │        │
│       │  │                                         │        │
│       │  │ claude -p - < prompt.txt                 │        │
│       │  │   --allowedTools "Read,Glob,Grep"       │        │
│       │  │   > /tmp/dual-scan-result.txt           │        │
│       │  └─────────────────────────────────────────┘        │
│       │                                                     │
│       ▼                                                     │
│  F5e: 读取 result.txt，与自己的结果在内存中对比               │
│  F5f: 追加 "### 双扫描交叉验证" 到已有报告                    │
│       │  标注 [Both] / [Agent-1:ClaudeCode] / [Agent-2:Codex]│
│       │                                                     │
│       ▼                                                     │
│  F6-F7: 冒泡 + HTML（正常流程）                              │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计决策

| 问题 | 解答 |
|------|------|
| Agent-2 是谁？ | 系统中安装的**另一个 AI CLI**（不是自己），通过 Bash 工具调用 |
| 如何区分自己？ | 当前 CLI 通过系统上下文已知自己的身份（Claude Code 或 Codex），从已安装的 CLI 中排除自己 |
| Agent-2 输出在哪？ | 写入临时文件 `{scan-output}/.dual-scan-result.txt`，由 Agent-1 读取后**可删除** |
| 会覆盖已有报告吗？ | **不会**。Agent-2 在只读模式运行（Codex: `-s read-only`，Claude: `--allowedTools "Read,Glob,Grep"`），无法写入 scan-output/ |
| Prompt 怎么传？ | 写入临时文件后通过 stdin 管道传入，避免 Windows 命令行长度限制 |

---

### F5a：检测可用的其他 CLI

```bash
# 检测系统中安装了哪些 AI CLI
where claude 2>/dev/null && echo "claude:found"
where codex 2>/dev/null && echo "codex:found"
```

**自身识别规则**：
- 如果你是 Claude Code → 你的身份标识是 `claude`
- 如果你是 Codex CLI → 你的身份标识是 `codex`

从检测到的 CLI 列表中**排除自己**，剩余的就是可用的"另一个 CLI"。

如果没有检测到其他 CLI → 跳过 F5，直接进入 F6。

### F5b：提示用户

```
Full 分析已完成。检测到系统中还安装了 {other_cli_name}。
是否使用 {other_cli_name} 对相同模块执行独立验证扫描？
两个不同 AI 的分析结果将交叉对比，标注各自发现和共识。
（{other_cli_name} 将以只读模式运行，不会修改任何已有文件）
```

- 用户拒绝 → 跳过，进入 F6
- 用户确认 → 继续 F5c

### F5c：构造 Prompt 文件

**铁律：不传递 Agent-1 的分析结论，避免锚定偏差。只传递"去哪里读源码"。**

将以下内容写入临时文件 `{scan-output}/.dual-scan-prompt.txt`：

```
你是独立的源码审计验证方。
你的分析必须完全独立，不要参考任何已有结论。

## 目标模块
{module_name_1}: {absolute_path_1}
{module_name_2}: {absolute_path_2}
...

## 分析规则
对每个模块：
1. 用 Glob 列出目录下所有源码文件（.h/.cpp/.java/.kt/.m/.swift/.ts 等）
2. 按语言惯例配对（如 foo.h + foo.cpp 一起读）
3. 逐个读取并分析：类/函数清单、依赖关系、质量问题
4. 检测跨文件功能重复
5. 给出四级判决之一：核心基石 / 提纯合并 / 重塑提取 / 彻底淘汰

判决标准：
- 核心基石：架构合理、代码活跃、被多模块依赖、无重复造轮子
- 提纯合并：核心逻辑有价值但有重复实现，需提取公共能力
- 重塑提取：业务有价值但架构严重老化，需新架构重写
- 彻底淘汰：长期无更新、无依赖、功能已被替代

## 输出格式（严格遵守）
对每个模块输出：

### {module_name}
- **判决**：{四级之一}
- **判决理由**：{一句话}
- **关键发现**：
  1. {发现描述}
  2. {发现描述}
  ...
- **横向对比**（如有功能重复）：
  - {对比发现}

## 禁止事项
- 不要写入或修改任何文件
- 不要读取任何 scan-output/ 目录下的文件
- 只读取源码文件
```

### F5d：调用另一个 CLI

根据检测到的另一个 CLI 类型，执行对应命令：

**如果另一个 CLI 是 Codex：**
```bash
codex exec - \
  -s read-only \
  -C "{project_dir}" \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  -o "{scan-output}/.dual-scan-result.txt" \
  < "{scan-output}/.dual-scan-prompt.txt"
```

**如果另一个 CLI 是 Claude Code：**
```bash
claude -p \
  --allowedTools "Read,Glob,Grep" \
  --dangerously-skip-permissions \
  < "{scan-output}/.dual-scan-prompt.txt" \
  > "{scan-output}/.dual-scan-result.txt"
```

> **超时**：Bash 调用设置 `timeout: 600000`（10 分钟）。如果超时，跳过双扫描，告知用户。

### F5e：解析 & 对比（Agent-1 在内存中完成）

1. 用 Read 工具读取 `{scan-output}/.dual-scan-result.txt`
2. 从文本中提取每个模块的判决和关键发现（按 `### module_name` 分割）
3. 逐模块与 Agent-1 自己的结果对比：
   - **判决对比**：一致 ✓ / 分歧 ✗
   - **发现归类**（语义匹配，不要求措辞一致）：
     - `[Both]`：两方均发现的同类问题（高可信度）
     - `[Agent-1:{self_cli}]`：仅当前 CLI 发现
     - `[Agent-2:{other_cli}]`：仅另一个 CLI 发现
   - **分歧解析**：判决不一致时，综合双方理由给出最终裁决

4. 清理临时文件：
```bash
rm -f "{scan-output}/.dual-scan-prompt.txt" "{scan-output}/.dual-scan-result.txt"
```

### F5f：追加到报告（唯一的持久写入）

将对比结果**追加**到 Agent-1 已写入的 .md 报告末尾。不创建新文件，不覆盖已有内容。

```markdown
### 双扫描交叉验证

#### 验证概况
- 验证模式：跨 CLI 独立分析
- Agent-1：{self_cli_name}（主分析方）
- Agent-2：{other_cli_name}（验证方，只读模式）
- 判决一致率：X/Y 模块（Z%）

#### 判决对比

| 模块 | Agent-1 判决 | Agent-2 判决 | 最终判决 | 一致性 |
|------|-------------|-------------|---------|--------|
| base | 核心基石 | 核心基石 | 核心基石 | ✓ |
| foo  | 提纯合并 | 重塑提取 | 提纯合并 | ✗ |

#### 发现对比明细

##### base
- [Both] FFmpeg 封装层线程安全问题（两方均独立发现，高可信度）
- [Agent-1:ClaudeCode] av_register_all 遗留调用
- [Agent-2:Codex] 缓冲区大小硬编码

##### foo
- [Both] 内存泄漏风险：缺少 RAII
- [Agent-2:Codex] 接口命名不一致

#### 分歧解析

##### foo — 判决分歧
- **Agent-1 (ClaudeCode)**：提纯合并 — 核心逻辑有价值，重复代码可合并
- **Agent-2 (Codex)**：重塑提取 — 架构严重老化，MFC 残留
- **最终裁决**：提纯合并 — MFC 残留仅限 UI 层，核心业务逻辑架构合理
```

---

## 与其他级别的关系

| 场景 | 推荐级别 |
|------|---------|
| 首次摸底数百模块 | `fast` |
| 常规审计 | `standard` |
| 重点模块深入 | `deep` |
| 整合前全面复核 | `full` |

- `full` 是独立模式，不需要先执行 standard 或 deep
- `full` 包含 `deep` 的所有检查项，额外增加：全文件覆盖 + 横向对比
- `full` 的判决冒泡和 HTML 生成机制复用 `deep` 的流程
- `full` 分析结果标注 `FULL` 徽章（紫色加金边），与 `DEEP` 徽章区分
