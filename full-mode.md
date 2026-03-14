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
│   └─ 如果已有 standard/deep 报告 → 仅作参考，不作为依赖
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
├─ Step F5：判决冒泡（复用 deep-mode.md 的冒泡机制）
│   └─ 与 deep 完全相同：逐级更新祖先 index.md
│
└─ Step F6：重新生成 HTML
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
