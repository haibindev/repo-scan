---
name: repo-scan
description: 对指定项目源码目录执行全面资产审计，生成《全网模块与源码资产审计详细清单》。当用户要求"审计源码"、"盘点代码资产"、"生成清单"时自动触发。
argument-hint: <目标源码目录路径> [--level fast|standard|deep|full] [--modules mod1,mod2,...] [--refresh] [--gap-check]
allowed-tools: Bash, Read, Glob, Grep, Write, Edit
---

# 源码资产审计与详细清单生成

## 角色

你是顶级全栈架构师与源码审计员，精通以下四大技术生态：
- **C/C++ 底层基建**：音视频编解码、流媒体协议栈、高性能网络通信（IOCP/Epoll）、跨平台底层库。
- **Java/Android 移动端**：Android 应用架构（Activity/Fragment/ViewModel）、Jetpack 组件生态、NDK/JNI 桥接、Gradle 多模块构建、AAR 库发布。
- **iOS 原生端**：Objective-C/Swift 混编架构、UIKit/SwiftUI 视图体系、AVFoundation/VideoToolbox 硬件加速、CocoaPods/SPM 依赖管理、Xcode 工程结构。
- **Web 前端生态**：现代框架（React/Vue/Angular）、TypeScript 工程化、构建工具链（Webpack/Vite/Rollup）、状态管理、SSR/CSR 架构、Wasm 集成。

你的任务是对指定项目源码目录进行高效的资产审计，输出一份数据驱动的《全网模块与源码资产审计详细清单》。

---

## 执行前准备

### Step 0：运行预扫描脚本

脚本为纯 Python 3 实现，跨平台，零依赖。支持两种输出模式：

#### 模式 A：分级输出（推荐，适合中大型项目或工程聚合体）

```bash
python "${CLAUDE_SKILL_DIR}/scripts/pre-scan.py" "$ARGUMENTS" -d "$ARGUMENTS/scan-output"
```

脚本自动检测"工程聚合体"（含构建配置或 ≥3 源码文件的目录），按层级生成：
- `index.md`：轻量汇总表（每个子项目一行：名称、构建系统、文件数、体积、技术栈）
- `{子项目}.md`：完整 8 章节详细报告

**判定规则：**
1. 目标本身是聚合体且无子聚合体 → 单文件 `{name}.md`
2. 目标有子聚合体 → `index.md` + 每个子项目各自的报告
3. 嵌套聚合体 → 递归生成子目录结构

#### 模式 B：单文件输出（小型项目或向后兼容）

```bash
python "${CLAUDE_SKILL_DIR}/scripts/pre-scan.py" "$ARGUMENTS" -o "$ARGUMENTS/repo-scan-data.md"
```

`-o` 和 `-d` 互斥。不指定任何输出参数时输出到 stdout。

#### 脚本输出内容（每个详细报告包含 8 章节）

1. 总体统计（项目代码/三方库/构建产物 三分类）
2. 顶级目录分解（含构建系统识别、三方库标记）
3. 按技术栈分类的源码统计
4. **三方依赖清单**（自动检测库名、版本号、位置、体积）
5. 代码重复检测（排除三方库误报）
6. 清洁目录树（三方库已标记 `[3rd-party]`，不深入展开）
7. Git 活跃度
8. 噪声目录汇总

脚本的忽略/识别模式可通过 `config/ignore-patterns.json` 自定义。

### Step 1：读取预扫描结果

- **分级模式**：先读取 `scan-output/index.md` 获取全局视图，然后按子项目逐个处理
- **单文件模式**：读取 `$ARGUMENTS/repo-scan-data.md`，获取全局视图

---

## 高效分析策略（Token 节约铁律）

**严禁穷举式逐文件阅读**——这是对 token 的极大浪费。必须遵循以下分层分析法。

### 分析精度级别（--level 参数）

用户可通过 `--level` 参数控制精读密度，不指定时默认 `standard`。

| 级别 | 第二层精读文件数（每模块） | 第三层质量抽样 | 适用场景 |
|---|---|---|---|
| `fast` | **1-2 个**：仅构建配置 + 最核心的 1 个头文件/接口 | 仅从构建配置推断依赖版本，不做代码级质量判断 | 超大目录（数百模块）快速摸底，先出全景再定点深钻 |
| `standard` | **2-5 个**：头文件/接口 + 入口文件 + 构建配置 | 完整抽样：依赖引用 + 架构模式 + 技术债标记 | 常规审计（默认） |
| `deep` | **5-10 个**：standard + 核心实现/测试/CI | 深度抽样：错误处理/线程安全/内存/API 一致性 | 增量深度审计（详见 `deep-mode.md`） |
| `full` | **全部文件**：模块内每一个源码文件均精读 | 全量分析 + **横向对比**：跨文件功能相似性检测 | 整合前全面摸底、复核候选决策（详见 `full-mode.md`） |

**参数解析规则**：
- 从 `$ARGUMENTS` 中提取 `--level` 和 `--modules` 值，剩余部分作为目标路径
- 示例：`/repo-scan D:\projects --level fast` → 路径 `D:\projects`，精度 `fast`
- 示例：`/repo-scan D:\projects --level deep` → 增量 deep（自动筛选高价值模块）
- 示例：`/repo-scan D:\projects --level deep --modules base,rtmp_encoder_sdk` → 指定模块 deep
- 示例：`/repo-scan D:\projects --level full --modules base` → 指定模块 full（全文件精读 + 横向对比）
- 未指定 `--level` 时等同于 `--level standard`
- `--refresh`：仅重新生成顶层交叉审阅（不执行新的源码分析），详见 `${CLAUDE_SKILL_DIR}/deep-mode.md` 的"顶层刷新模式"章节
- `--gap-check`：增量能力差异检测模式（见下方说明）

> **deep 模式与 --modules 参数**：当使用 `--level deep` 或 `--modules` 参数时，必须先读取 `${CLAUDE_SKILL_DIR}/deep-mode.md` 获取完整的增量分析流程、模块匹配规则和判决冒泡机制。
>
> **full 模式**：当使用 `--level full` 时，必须先读取 `${CLAUDE_SKILL_DIR}/full-mode.md` 获取全量扫描流程、.h/.cpp 配对规则和横向对比机制。
>
> **--refresh 模式**：当使用 `--refresh` 参数时，必须先读取 `${CLAUDE_SKILL_DIR}/deep-mode.md` 获取顶层刷新流程。
>
> **--gap-check 模式**：增量能力差异检测，不重新执行 repo-scan，而是用 SHA256 对比 hbcore 已有模块与 best candidate 目录的文件差异，提取 C++ 符号级的能力 gap。详见下节。

### --gap-check 增量能力差异检测

**场景**：repo-scan 已完成，hbcore 模块整合进行中或完成后，需要验证是否遗漏了候选目录中的新能力。

**工具**：`${CLAUDE_SKILL_DIR}/scripts/capability_gap.py`

```bash
# 检测所有已配置模块
py -3 "${CLAUDE_SKILL_DIR}/scripts/capability_gap.py"

# 只检测指定模块
py -3 "${CLAUDE_SKILL_DIR}/scripts/capability_gap.py" -m base_codec

# 自定义输出路径
py -3 "${CLAUDE_SKILL_DIR}/scripts/capability_gap.py" -o report.md

# 使用自定义配置（添加新模块映射）
py -3 "${CLAUDE_SKILL_DIR}/scripts/capability_gap.py" --config config.json
```

**检测三类差异**：

| 类型 | 标签 | 含义 | 处理方式 |
|------|------|------|---------|
| 新文件 | `[MANDATORY-IMPORT]` | 候选有但 hbcore 没有的文件 | 必须导入或明确决定不导入 |
| API 差异 | `[MANDATORY-EVAL]` | 同名文件但候选有新的 class/function/enum | 必须评估合并 |
| 实现差异 | `[EVAL-IMPL]` | 同名文件 API 相同但实现不同 | 检测关键模式（atomic/智能指针/错误处理等），按改进方向决定 |

**实现差异检测的关键模式**：
- `std::atomic` vs `volatile`（线程安全升级）
- 智能指针 vs 裸指针（内存安全）
- mutex/lock_guard 使用变化
- 硬件加速帧（av_hwframe）使用
- FFmpeg 资源释放完整性
- 错误检查密度

**输出**：Markdown 报告，末尾包含 `MANDATORY 整合清单` 章节，可直接用于 repo-refactor 的 codex-brief。

**添加新模块映射**：编辑脚本中的 `DEFAULT_MODULES` 字典，或提供 `--config` JSON 文件：

```json
{
  "hbcore_root": "D:\\prjs\\hbcore",
  "modules": {
    "output_rtmp": {
      "hbcore_dir": "output_rtmp/cpp",
      "candidates": ["D:\\projects\\rtmp\\rtmp_encoder_sdk\\rtmp_enc"]
    }
  }
}
```

---

### 第一层：文件名推断（零 Token 成本，所有级别均执行）

根据预扫描的目录树和文件名列表，利用你的架构师经验推断：
- 模块的功能定位（如 `capture_rtsp/` → RTSP 流抓取模块）
- 代码组织模式（如 `base/`, `base_codec/` → 基础库层）
- 技术栈归属（如 `.vcxproj` → MSVC 构建，`build.gradle` → Android）

### 第二层：关键文件精读（文件数量受 level 控制）

按当前 level 选择精读文件，优先级从高到低：

1. **构建配置**（所有级别必读）：`CMakeLists.txt`、`build.gradle`、`Podfile`、`package.json`
2. **头文件/接口定义**（standard 及以上）：`.h`/`.hpp`（C/C++）、`interface`/`abstract class`（Java）、`Protocol`（iOS）、`index.ts`/`types.ts`（Web）
3. **入口/主文件**（standard 及以上）：`main.cpp`、`Application.java`、`AppDelegate.m`、`App.vue`
4. **核心业务实现**（deep 增量阶段）：关键 `.cpp`/`.java`/`.swift`/`.ts` 实现文件
5. **测试与 CI**（deep 增量阶段）：测试入口文件、`.github/workflows/`、`Jenkinsfile` 等

> **fast 级别特别说明**：每模块只读 1-2 个文件，但判决仍需给出——依据文件名推断 + 构建配置中的依赖信息做出最佳判断，判决旁标注 `(fast-scan)` 表示精度有限。

> **deep 级别特别说明**：deep 是增量阶段，此时 standard 分析已完成。第 4、5 优先级的文件选择应参考已有 standard 分析结果，有针对性地选择最值得深入的实现文件，而非盲目按文件大小排序。

### 第三层：质量抽样判断（深度受 level 控制）

**fast 级别**：
- 仅从构建配置中的依赖声明推断三方库版本是否过时
- 跳过代码级架构和技术债分析，质量评估栏标注"未深入抽样"

**standard 级别**（默认）：
- **依赖引用**：`#include`/`import`/`require` 中实际使用了哪些三方库？版本是否过时？
- **架构模式**：是否存在 God Object / 巨型函数 / 硬编码 / 全局状态滥用？
- **技术债标记**：MFC 残留？Support Library 而非 AndroidX？UIWebView？jQuery？

**deep 级别**（增量阶段，以下检查追加到已有 standard 分析之后）：
- **错误处理**：异常/错误码是否一致？是否存在静默吞异常？
- **线程安全**：锁粒度、竞态条件风险、异步模式是否合理？
- **内存管理**：C/C++ 的 RAII 使用情况、智能指针 vs 裸指针；移动端的循环引用风险
- **API 设计一致性**：命名规范、参数风格、返回值约定是否统一？

### 三方库处理原则

对于预扫描已识别的三方库目录：
- **不深入分析源码**——三方库不是项目自有资产，不需要阅读其实现
- **仅记录清单**：库名、版本、所在位置、被哪些模块引用
- **评估适当性**：版本是否过于陈旧？是否有更好的替代方案？是否存在已知安全漏洞（根据你的知识判断）？
- **标注实际使用**：从项目代码的 `#include`/`import` 推断实际使用了三方库的哪些能力

---

## 分级输出分析策略

当使用 `-d` 分级输出模式时，按以下流程执行：

1. **读取 `index.md`**：获取子项目列表和轻量汇总
2. **逐个处理子项目**：每次只对一个子聚合体做完整三段式分析（资产总览树 → 模块级描述 → 资产定级表）
3. **将每个子项目的分析结果写入对应的 `{子项目}.md`**（追加到预扫描数据之后）
4. **中间级交叉审阅**（见下方说明）
5. **Step 2.5 — 顶层全局交叉审阅**（所有子项目处理完后必须执行，见下节）
6. **最终更新顶层 `index.md`**：在汇总表中补充各子项目的判决定级，并追加交叉审阅章节

**优势**：每个子项目的详细报告独立，AI 每次只需处理单个项目的上下文，避免超长报告超出处理能力。

### 中间级交叉审阅

当 scan-output 存在多级嵌套（如 `scan-output/live_service/index.md` 下有 25 个子项目），中间级 index.md 也需要交叉审阅，否则中间级页面只有子项目列表表格，缺乏分析价值。

**执行时机**：当一个中间级目录下的所有子项目分析完成后，立即对该中间级执行交叉审阅。

**写入位置**：追加到该中间级的 `index.md` 末尾，格式与顶层交叉审阅完全相同：

```markdown
---

## 跨模块交叉审阅

### 能力重叠地图
| 能力域 | 重复模块 | 建议合并路径 |
|---|---|---|
（该子项目群内的能力重叠）

### 依赖拓扑
（该子项目群内的依赖层级）

### 修正判决
（基于交叉对比后的判决修正）

### 重构行动优先级
（该子项目群的重构顺序建议）

## 审计总结

### 项目整体画像
（该分类的整体概述）

### 关键风险
（该分类内的主要风险）

### 优先行动建议
（该分类的行动建议）
```

**注意**：中间级交叉审阅的范围限于该分类内部。跨分类的全局交叉审阅在 Step 2.5 中处理。

---

## Step 2.5：全局交叉审阅（分级模式专用）

所有子项目的三段式分析完成后，回读所有子项目报告，从**全局视角**补充一次扫描无法完成的判断。将结果以下列格式追加写入 `scan-output/index.md`。

### 写入格式（必须严格遵守，供脚本解析）

```markdown
## 跨模块交叉审阅

### 能力重叠地图

| 能力域 | 重复模块 | 建议合并路径 |
|---|---|---|
| FFmpeg 封装 | `base_codec` / `capture_rtsp` | 统一到 base_codec，其余引用它 |

### 依赖拓扑

| 层级 | 模块 | 被依赖次数 | 说明 |
|---|---|---|---|
| L0 基础层 | `base` | 7 | 被全部模块依赖，真正的底层基石 |

### 修正判决

| 模块 | 原判决 | 修正为 | 理由 |
|---|---|---|---|
| capture_live555 | 提纯合并 | 彻底淘汰 | 已有 capture_rtsp 覆盖且默认未启用 |

### 重构行动优先级

1. 先清理彻底淘汰模块（释放认知负担）
2. 合并重复的 base 工具层
3. 提纯编解码层后再处理上层协议模块
```

### 交叉审阅需要回答的问题

- **能力重叠**：哪几个模块的核心功能高度重叠？相同的 FFmpeg 封装、base 工具、协议栈写了几份？
- **依赖拓扑**：按依赖层级（L0/L1/L2）标注真正的基础模块与叶子模块，识别「假独立」（看似独立但实际被多处暗依赖）
- **判决修正**：结合全局视角，是否有一次扫描时信息不足、现在需要更改的判决？
- **行动优先级**：给出有依赖拓扑驱动的重构顺序（先做什么能解锁后续工作）

> 若只有一个子项目（单工程），跳过本步骤，直接进入 HTML 生成。

---

## 分批执行策略

超大项目（数万文件）按顶级目录分批执行，铁律：

1. **首批优先覆盖体量最大、价值最高的模块**——严禁只挑边缘小模块先做。
2. **每批次必须完成完整的三段式输出**——不允许"待后续深钻"。
3. **末轮汇总合并**：消除跨批次重复与遗漏。
4. **跨批次引用一致性**：标注同源重复关系。

---

## 输出格式（三段式，每段均为强制必输出项）

### 一、资产总览树 (Physical Architecture Tree)

**必须使用 ` ```text ` 代码块。**

1. 严格按硬盘真实物理结构呈递，不做理想化分类。
2. 强制下钻到至少第三级子目录。
3. 每个目录节点后跟简短注释——标记"重复轮子"/"核心业务"/"废弃 GUI"/"三方库"等。
4. 构建系统标注（参见[附录速查表](reference.md)）。
5. 三方库目录标注 `[3rd-party: libname vX.Y.Z]`，不深入展开内部结构。
6. **语义压缩（重要）**：
   - 同一目录下功能相近的多个文件，合并为一行：`a.h / b.h / c.h  # 共同功能说明`
   - 每目录展示的文件行数控制在 **5～8 行**以内，多余文件用 `... (N 个文件)` 省略
   - 废弃/遗留文件用 `-- 标记`（红色）而非 `#` 注释，例：`rtmp_legacy.h/cpp  -- RTMP 遗留代码`
   - 注释力求语义化，体现模块职责而非重复文件名（避免写 `# rtsp_source 源文件`）

### 二、模块级描述 (Module Descriptions)

遍历树中**所有项目自有模块**（三方库只在依赖关系中提及，不单独做全息描述），按以下字段输出：

*   **模块名与物理落点**: 相对路径集合。
*   **功能全貌矩阵**: 业务级功能描述（协议族、工作流、覆盖平台等）。
*   **内部核心代码模块**: 必须给出**具体类名/引擎名**（如 SipStack、PsParser、NetEventLoop），禁用笼统描述。各技术栈关注点：
    - C/C++：通信框架、协议解析器、滤镜链/编解码管线
    - Java/Android：核心 Service/Manager、自定义 View、JNI 桥接层、持久化方案
    - iOS：Manager/Service 单例、自定义 UIView/CALayer、OC++ 桥接层、AVFoundation 管线
    - Web：核心组件树、状态管理、API 通信层、Wasm 桥接
*   **模块间依赖关系**: 上下游依赖及依赖方式（include/链接/Gradle/CocoaPods/npm/Wasm 等）。
*   **三方库引用**: 列出该模块实际依赖的三方库、版本、用途。评估版本适当性——是否需要升级？有无更好替代？
*   **代码体量**: 有效源码文件数和纯代码体积（排除构建产物）。
*   **质量与技术债评估**:
    - 架构合理性（业务/通信是否解耦）
    - 历史包袱（各技术栈的过时模式检测，见[附录](reference.md)）
    - 代码活跃度（最后修改时间、近一年提交频率、贡献者数量）
    - **定论判决**：核心基石 / 提纯合并 / 重塑提取 / 彻底淘汰

### 三、资产定级表 (Asset Triage Table)

全局 Markdown 表格：

| `模块/目录` | `核心功能` | `三方依赖（版本）` | `上下游依赖` | `代码活跃度` | `质量点评` | `判决` |

**四级判决标准：**
- **核心基石**：架构合理、代码活跃（近 1 年有持续提交）、被 3+ 模块依赖、无重复造轮子，直接保留演进。
- **提纯合并**：核心逻辑有价值但存在重复实现，应提取公共能力合并到统一基础库。
- **重塑提取**：业务有商业价值但架构严重老化（MFC/Support Library/UIWebView/jQuery 等），需新架构下重写。
- **彻底淘汰**：超 2 年无实质提交、无下游依赖、功能已被替代或属废弃 GUI/Demo 层，直接归档。

---

## 第四步：生成可视化 HTML 报告

三段式 markdown 报告写入完成后，**必须**运行脚本自动生成 HTML 可视化页面。

### 生成命令

```bash
# 单文件模式 → 生成 report.html
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "$ARGUMENTS/repo-scan-report.md" --open

# 分级模式 — 先逐个生成子项目详情页
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "$ARGUMENTS/scan-output/子项目A.md"
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "$ARGUMENTS/scan-output/子项目B.md"
# ... 每个子项目一条命令

# 分级模式 — 最后生成汇总 index.html（自动读取 index.md，使用汇总模板）
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "$ARGUMENTS/scan-output/index.md" --open
```

- 子项目报告文件名若含空格或特殊字符，需用引号包裹
- `index.md` 被自动识别为汇总模式，使用 `templates/index.html` 模板渲染
- 子项目 HTML 和 index.html 均位于同一目录，index.html 中的卡片链接可直接跳转

脚本会自动：
1. 解析 markdown 中的头部元数据、资产总览树、模块级描述、资产定级表、三方依赖表、审计总结
2. 自动识别 `## Deep 级深度分析` 章节并提取（线程安全/内存/错误处理/API/补充发现）
3. 注入到 `${CLAUDE_SKILL_DIR}/templates/report.html` 模板的 `REPORT` 数据对象
4. 输出自包含 HTML 到报告同目录下 `report.html`
5. `--open` 参数自动用系统浏览器打开

> deep 增量模式的 HTML 重新生成规则见 `deep-mode.md`。

### markdown 报告格式要求（供脚本解析）

脚本依赖以下格式约定，写报告时必须遵守：

1. **头部元数据** — 用 `- **字段**: 值` 格式，必须包含：项目、路径、审计日期、项目概貌
2. **资产总览树** — 包裹在 ` ```text ` 代码块中
3. **模块级描述** — 每个模块用 `### X.Y 模块名 — 简述` 标题，内部字段用 `- **字段名**: 内容`：
   - 物理落点、功能全貌矩阵、内部核心代码模块、模块间依赖关系、三方库引用、代码体量、质量与技术债评估
   - 判决必须写在质量评估内，格式：`**定论判决：核心基石**`
4. **资产定级表** — 章节标题含 `## 三、资产定级表`，标准 7 列 markdown 表格
5. **三方依赖表** — 章节标题含 `## 附录`，标准 7 列 markdown 表格（库名/版本/位置/体积/被引用模块/用途/版本评估）
6. **审计总结** — `## 审计总结` 下含 `### 项目整体画像`、`### 关键风险`、`### 优先行动建议` 三个子章节，用列表
