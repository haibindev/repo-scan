# Deep 增量分析模式

> 本文件定义 `--level deep` 和 `--modules` 参数的完整行为。仅在使用这些参数时需要读取。

## `--modules` 模块匹配规则

`--modules` 接受逗号分隔的模块标识符列表。目标路径始终是原始扫描的根目录（如 `D:\projects`），`--modules` 负责定位具体模块。

**匹配优先级**（从高到低）：

1. **精确路径匹配** — 值含 `/` 或 `\` 时，视为 scan-output 内的相对路径，直接定位 .md 文件
   ```
   --modules live_service/hbs_28181_streaming/hbs_28181_server
   → 查找 scan-output/live_service/hbs_28181_streaming/hbs_28181_server/index.md
     或 scan-output/live_service/hbs_28181_streaming/hbs_28181_server.md
   ```

2. **唯一名称匹配** — 值不含路径分隔符时，在整个 scan-output 目录树中搜索同名 .md 文件或同名目录下的 index.md
   ```
   --modules hbs_28181_server
   → 递归搜索 scan-output/**/hbs_28181_server/index.md 或 **/hbs_28181_server.md
   → 如果唯一命中 → 使用
   → 如果多个命中 → 列出所有匹配项，要求用户用路径前缀消歧
   ```

3. **模糊前缀匹配** — 允许省略中间层级，只要尾部路径唯一
   ```
   --modules hbs_28181_streaming/hbs_28181_server
   → 匹配 scan-output/live_service/hbs_28181_streaming/hbs_28181_server
   ```

**同名冲突处理**：当多个模块同名时（如 `live_service/.../base` 和 `media_cross/base`），AI 必须列出冲突项并提示用户加路径前缀：
```
发现 3 个名为 "base" 的模块：
  1. live_service/hbs_28181_streaming/base
  2. live_service/webrtc_server_lib/base
  3. media_cross/base
请用路径前缀指定，如：--modules media_cross/base
```

**使用示例**：
```bash
# 精确路径（无歧义）
/repo-scan D:\projects --level deep --modules live_service/hbs_28181_streaming/hbs_28181_server

# 唯一名称（只有一个叫这个名字的模块）
/repo-scan D:\projects --level deep --modules hbs_28181_server

# 混合指定多个
/repo-scan D:\projects --level deep --modules hbs_28181_server,media_cross/base,rtmp_encoder_sdk

# 省略中间层级
/repo-scan D:\projects --level deep --modules hbs_28181_streaming/hbs_28181_server
```

## Deep 增量执行流程

**deep 不是独立的全量扫描，而是在已有 standard/fast 数据基础上的增量深度分析。**

#### 执行流程

```
--level deep 触发后：
│
├─ Step D0：检测已有数据
│   ├─ scan-output 目录存在且有 .md 文件？
│   │   ├─ 是 → 进入增量模式（Step D1）
│   │   └─ 否 → 先以 standard 级别执行完整扫描，完成后自动进入 Step D1
│   │
├─ Step D1：筛选 deep 目标模块
│   ├─ 用户指定了 --modules？
│   │   ├─ 是 → 使用用户指定的模块列表
│   │   └─ 否 → 自动筛选（见下方规则）
│   │
├─ Step D2：对每个目标模块执行 deep 精读（5-10 个文件）
│   ├─ 读取已有 .md 了解 standard 分析结果（避免重复工作）
│   ├─ 精读核心实现文件、测试文件、CI 配置
│   └─ 执行深度质量抽样（线程安全/内存/错误处理/API一致性）
│
├─ Step D3：将 deep 分析追加到已有 .md 文件末尾
│
├─ Step D4：判决冒泡（见下方"判决冒泡机制"）
│   ├─ deep 发现是否改变了该模块的判决？
│   │   ├─ 是 → 在 deep 分析末尾写入 `### 判决修正`
│   │   └─ 否 → 跳过
│   ├─ **按所有祖先层级分组**：将 deep 模块按其所属的每一级 index.md 分组
│   │   例：--modules gui_wrapper/Demo,record/camera → 受影响的层级为：
│   │   - gui_wrapper/Demo/index.md（Demo 的直接父级）
│   │   - gui_wrapper/index.md（Demo 的祖父级）
│   │   - record/camera/index.md（camera 的直接父级）
│   │   - record/index.md（camera 的祖父级）
│   │   即：从 deep 模块路径向上遍历直到 scan-output 根目录，每一级 index.md 都需要更新
│   ├─ **逐级更新交叉审阅**：对每个受影响层级的 index.md（从最内层到最外层）：
│   │   ├─ 回读该层级下所有子模块报告（含新增 deep 分析）
│   │   ├─ 如果该 index.md 尚无交叉审阅章节 → 补写完整章节
│   │   └─ 如果已有交叉审阅 → 追加/更新 deep 发现（共性Bug模式、修正判决、行动优先级）
│   └─ **必须更新顶级 index.md**（见下方"顶级交叉审阅更新"）
│
└─ Step D5：重新生成**所有受影响层级**的 HTML
    ├─ 每个被 deep 分析的模块 HTML
    ├─ **每个受影响的父级** index.html（不止一个！）
    └─ **顶级 index.html（必须，因 D4 总会更新顶级 index.md）**
```

#### 向下递归规则（第 N 层 deep 时若子级仍有目录）

**触发条件**：对某个模块执行 deep 分析时，发现该模块的**直接子级仍然是目录**（而非最底层代码文件），说明当前层级是"项目级"而非"模块级"，direct 的 deep 精读价值有限。

**规则**：
1. 在 Step D2 执行 deep 精读**之前**，先检查目标目录的子级是否含有子目录
2. 若是 → **自动向下扩展**：对每个子目录递归执行完整 deep 流程（D2→D3→D4），构建下一层分析
3. 所有子目录的 deep 分析完成后，再对当前层执行**交叉审阅更新**（Step D4 的逐级更新部分）
4. 若否（子级全部是代码文件）→ 按正常流程对当前层 deep 精读

**示例**：
```
--modules rtmp/rtmp_player_cross
→ 检查 rtmp_player_cross/ 的子级：base/, base_codec/, player/, capture_rtmp/, ... 均为目录
→ 自动对每个子目录 deep：
    deep(rtmp_player_cross/base)          # 第4层 deep
    deep(rtmp_player_cross/base_codec)    # 第4层 deep
    deep(rtmp_player_cross/player)        # 第4层 deep
    ...
→ 所有子目录 deep 完成后，更新 rtmp_player_cross/index.md 交叉审阅
→ 继续冒泡：更新 rtmp/index.md → 更新顶级 index.md
```

**深度上限**：最多递归到第 5 层（防止过度展开）。第 5 层以下若仍有子目录，记录到 index.md 的 `### 未展开子目录` 章节，供后续手动指定。

#### 自动筛选规则（无 --modules 时）

从已有 standard 数据中，按以下优先级选取模块：

1. **判决为"核心基石"的模块** — 全部入选（这些是底层基石，deep 分析价值最高）
2. **判决为"提纯合并"的模块** — 全部入选（即将整合，需要精确了解内部质量）
3. **判决为"重塑提取"且代码体量前 30% 的模块** — 体量大的重塑模块值得深入
4. **"彻底淘汰"模块** — 不入选（无 deep 分析价值）

**数量上限**：单次 deep 分析不超过 **20 个模块**。超出时按上述优先级截断，并告知用户可用 `--modules` 指定其余模块。

#### deep 分析输出格式（追加到已有 .md 末尾）

```markdown
## Deep 级深度分析

### 精读文件清单
1. `path/to/file.cpp` — 简述为什么选这个文件
2. `path/to/file.h` — ...
（5-10 个文件）

### 并发与线程安全评估
- **锁/同步策略**: （C++: mutex/atomic; Java: synchronized/ReentrantLock; Go: channel/mutex; Rust: Send/Sync; Swift: actor/DispatchQueue）
- **竞态风险**: ...
- **异步模式**: （C++: 回调/future; Kotlin: 协程; Swift: async/await; JS/TS: Promise/async; Go: goroutine）

### 资源与内存管理评估
- **生命周期管理**: （C++: RAII/智能指针; Java/Kotlin: GC+Closeable; Swift/ObjC: ARC+weak/unowned; Rust: 所有权; Go: defer）
- **泄漏风险**: （C++: 裸指针; ObjC/Swift: 循环引用; Java: 未关闭资源; Go: goroutine 泄漏）
- **unsafe/FFI 边界**: （如有跨语言调用）

### 错误处理评估
- **错误传播一致性**: （C++: 错误码/异常; Java: checked/unchecked; Go: error return; Rust: Result/Option; Swift: throws）
- **静默吞错误**: ...

### API 设计一致性
- **命名规范**: （是否遵循语言惯例：C++ snake_case, Java/Kotlin camelCase, Go PascalCase 导出等）
- **参数风格**: ...
- **返回值约定**: ...

### Deep 级补充发现
1. （standard 级未发现的重要问题）
2. ...
```

#### 判决冒泡机制（deep 后必须执行）

deep 分析可能发现 standard 级别未察觉的严重问题（如 crash bug、内存泄漏、线程安全缺陷），从而改变模块判决。此时需要**逐级向上冒泡**更新。

**Step D4 详细流程：**

1. **模块级判决修正**：如果 deep 发现改变了判决（如"核心基石"降为"重塑提取"），在该模块的 `## Deep 级深度分析` 末尾追加：
   ```markdown
   ### 判决修正
   - **原判决**: 核心基石
   - **修正为**: 重塑提取
   - **修正理由**: deep 分析发现 volatile bool 替代 atomic、Stop() 释放顺序导致必崩等系统性缺陷，
     当前代码质量不足以作为基石直接复用，需要重塑后才能整合。
   ```

2. **祖先层级交叉审阅更新（逐级执行，从内到外）**：
   - **关键**：不仅是直接父级，从 deep 模块路径向上到 scan-output 根的**每一级 index.md** 都必须更新
   - 例：`--modules gui_wrapper/Demo` 影响了：
     - `gui_wrapper/Demo/index.md`（直接父级，Demo 内部子项目的交叉审阅）
     - `gui_wrapper/index.md`（祖父级，gui_wrapper 内所有子项目的交叉审阅）
   - 例：`--modules rtsp/a,rtsp/b,rtmp/c` 影响了 `rtsp/index.md` 和 `rtmp/index.md` 两个父级
   - 对每个受影响层级的 index.md：
     - 回读该层级下所有子模块报告（含新增 deep 分析）
     - 更新/追加 `## 跨模块交叉审阅`（含共性Bug模式、修正判决、行动优先级）
     - 如果该 index.md 还没有交叉审阅章节，此时补写完整章节（含审计总结）

3. **顶级交叉审阅更新（必须执行，不论判决是否变化）**：
   deep 分析产出的价值不仅是判决修正，还包括跨模块共性 Bug 模式、风险确认、行动优先级调整等。因此顶级 index.md **每次 deep 分析后都必须更新**，具体内容：
   - 在 `## 跨模块交叉审阅` 中追加/更新 `### 共性Bug模式（Deep 级发现）` 表——汇总所有 deep 模块组发现的跨模块 Bug 模式（volatile 误用、时间炸弹、内存泄漏等）
   - 更新 `### 全局关键风险` 表——将 deep 确认的风险标注"Deep 确认"并调整严重度
   - 更新 `### 重构行动优先级`——将"修复 Deep 确认的必修 Bug"提升为最高优先级
   - 如有判决变化，同步更新 `## 全局资产判决汇总` 表和 `### 修正判决` 表

**判决只降不升原则**：deep 分析通常发现问题而非优点，所以判决修正大多是**降级**。极少数情况下 deep 分析发现模块质量远超预期（如 standard 因文件名误判为废弃但实际代码活跃），也允许升级，但需详细说明理由。

#### 并行执行策略

对于多个 deep 目标模块，使用 Agent 工具并行处理：
- 按关联度分组（如同一子项目下的模块分到一组）
- 每组 3-5 个模块，启动一个 Agent
- 最多同时 3-4 个 Agent 并行
- 每个 Agent 独立读取源码、独立写入对应 .md 文件

## Deep 模式 HTML 重新生成

deep 分析完成后，需重新生成**所有受影响层级**的 HTML。从 deep 模块向上到顶级的每一级都要重新生成：
```bash
# 例：--modules gui_wrapper/Demo,rtmp/rtmp_encoder

# 1. 重新生成被 deep 分析的每个模块页面
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/gui_wrapper/Demo/子项目.md"
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/rtmp/rtmp_encoder/index.md"

# 2. 重新生成每个受影响的祖先 index（从内到外每一级！）
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/gui_wrapper/Demo/index.md"   # 直接父级
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/gui_wrapper/index.md"        # 祖父级
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/rtmp/index.md"               # 直接父级

# 3. 重新生成顶级 index
python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/index.md" --open
```

HTML 模板的 deep 相关特性：
- **页面标题徽章**：含 deep 分析的页面标题显示紫色 `DEEP` 徽章
- **项目卡片徽章**：子项目列表中，有 deep 分析的项目名称后显示 `DEEP ×N`（N 为 deep 模块数）
- **独立 DEEP 章节**：紫色左边框 + 渐变标题，与 standard 内容明确区分
- **verdict 聚合**：子目录 index 页面自动从子模块 .md 中聚合判决分布数据

---

## 顶层刷新模式（`--refresh`）

当中间层级的交叉审阅已更新（如 deep 分析后补写/修改了父级 index.md），但顶层 index.md 的全局交叉审阅尚未同步时，使用 `--refresh` 单独刷新顶层。

**典型场景**：
- deep 分析完成后，中间层级交叉审阅产生了新的判决修正、共性 Bug 模式，需要汇总到顶层
- 多轮 deep 分析分批执行，每轮更新了不同的中间层级，最后统一刷新顶层
- 手动修改了某些子项目的判决或分析内容，需要重新聚合顶层

**使用方式**：
```bash
/repo-scan D:\projects --refresh
```

**执行流程（R0-R3）**：

```
--refresh 触发后：
│
├─ Step R0：读取 scan-output/index.md 获取全部子项目列表
│
├─ Step R1：回读所有中间层级 index.md 的交叉审阅章节
│   ├─ 提取每个分类的：判决分布、能力重叠、共性Bug模式、修正判决、关键风险
│   └─ 如果某中间层级缺少交叉审阅 → 跳过（不自动补写，仅汇总已有数据）
│
├─ Step R2：重新生成顶层 index.md 的以下章节
│   ├─ `## 全局资产判决汇总` — 重新统计各分类的判决分布数字
│   ├─ `## 跨模块交叉审阅`
│   │   ├─ `### 能力重叠地图` — 合并各分类的重叠发现，去重，保留跨分类重叠
│   │   ├─ `### 共性Bug模式（Deep 级发现）` — 汇总所有中间层级的 bug 模式表
│   │   ├─ `### 修正判决` — 合并所有中间层级的判决修正
│   │   ├─ `### 重构行动优先级` — 基于最新数据重新排序
│   │   └─ `### 全局关键风险` — 基于最新数据更新风险表
│   └─ 保留顶层 index.md 中 `## 跨模块交叉审阅` 之前的所有内容不变
│
└─ Step R3：重新生成顶层 HTML
    python "${CLAUDE_SKILL_DIR}/scripts/gen_html.py" "scan-output/index.md" --open
```

**与 `--level deep` 的关系**：
- `--level deep` 的 Step D4 中包含顶层更新，但那是作为 deep 流程的一部分自动执行的
- `--refresh` 是独立命令，不执行任何源码分析，仅基于已有 .md 数据重新聚合顶层
- 如果 deep 流程正常完成了 D4，通常不需要额外 `--refresh`；`--refresh` 用于补救遗漏或手动修改后的同步
