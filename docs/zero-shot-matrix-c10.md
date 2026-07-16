# C10: 12-driver zero-shot matrix

## 1. 目标与约束

C10 的目标是让冻结的 12-driver holdout 全部获得可审计 compile context，并从统一矩阵中机器识别第一个覆盖至少三个驱动的公共语义 blocker。冻结集合、source SHA、Linux commit 和 specialization guard 均未改变；extractor/ 和 generator/ 没有增加任何 holdout driver-name、basename 或私有前缀特例。

这一步区分三个概念：

- exact context：真实 Kbuild object command 可追溯，不是 include guess；
- compile：生成 C 被对应工具链接受；
- strict-ready：识别出的寄存器语义、路径、值、callback 和 backend binding 满足现有严格 gate。

三者不能互相替代。

## 2. Compile-context materialization

`drivers/holdout/zero-shot-v1-contexts.json` 固定 7 个 profile：

| Profile | Arch/defconfig | Holdout 数 | 说明 |
|---|---|---:|---|
| arm-v4t | ARM `multi_v4t_defconfig` | 2 | native architecture context |
| arm-v7 | ARM `multi_v7_defconfig` | 3 | native architecture context |
| arm-moxart | ARM `moxart_defconfig` | 1 | native architecture context |
| arm-v5 | ARM `multi_v5_defconfig` | 1 | native architecture context |
| arm-dove | ARM `dove_defconfig` | 1 | native architecture context |
| powerpc-wii | PowerPC `wii_defconfig` | 1 | native；需要 `ld.lld` |
| x86-pinned | 固定实验 build | 3 | pinned object context |

`verification/materialize_holdout_contexts.py` 对每个 profile 配置 build、构建显式 object target、读取对应 `.cmd`，然后生成合并的 `output/zero-shot-contexts/compile_commands.json`。版本化报告记录 profile、`.config` SHA、`.cmd` SHA、raw command SHA、编译器版本和解析后的参数 SHA。

`gpio-ge` 是明确的限制：原生 85xx profile 会给 clang-18 传入不支持的 `-mcpu=8540`，因此 recipe 使用显式 x86 object context，并记录 non-native note。它仍是 exact Kbuild command，但不是 native-architecture context，报告不得混淆这两个维度。

结果为 12/12 exact contexts，其中 9 个来自对应架构 defconfig，3 个来自 pinned x86 build。

## 3. Matrix 与 blocker 聚类

`verification/run_zero_shot_matrix.py` 对 12 个案例统一使用合并 compile database 和 `--compile-context required`。每一行记录：

- context origin、profile、architecture、provenance 和参数/raw-command SHA；
- function、RIS operation、source-access accounting 和 clang diagnostics；
- 三后端 compile、unsupported marker 与 strict readiness；
- raw blocker 和稳定的 normalized category。

聚类先按 driver 去重，再按覆盖数降序、category 名称稳定打破平局。`linux_semantic_binding` 是 umbrella，不参与“第一个公共根因”的选择。

当前矩阵：

| 指标 | 结果 |
|---|---:|
| exact context | 12/12 |
| pipeline completed | 12/12 |
| harness compile | 12/12 |
| bare-metal compile | 12/12 |
| Linux compile | 12/12 |
| harness strict-ready | 3/12 |
| bare-metal strict-ready | 3/12 |
| Linux strict-ready | 3/12 |

三个 strict-ready 驱动是三个 clock 案例：`clk-fixed-mmio`、`clk-moxart`、`clk-nspire`。

机器聚类结果：

| Category | Driver 数 |
|---|---:|
| `no_register_access` | 7 |
| `linux_semantic_binding` | 5（umbrella） |
| `callback_binding` | 2 |
| `clang_diagnostics` | 2 |
| `missing_role` | 2 |
| `conservative_loop` | 1 |

因此首个公共语义 blocker 是 `no_register_access`，覆盖 7/12：四个 GPIO/IRQ、两个 SDHCI 和一个 virtio 案例。其含义不是这些驱动没有硬件操作，而是寄存器语义隐藏在 subsystem helper、callback/private object 或库实现中，当前单源提取没有把它们恢复成 RIS。

## 4. 过程中暴露的问题

### 4.1 空 RIS module 导致 pipeline 越界退出

首轮矩阵中 6 个零操作案例已生成 `analysis.json`，随后 harness trace 选择逻辑直接访问 `modules[0]`，触发 `IndexError`。矩阵最初把“analysis 文件存在”误记为 pipeline completed，形成了错误的 12/12 表象。

修复包括：

- driver pipeline 对空 module 使用空 trace expectation，不再越界；
- matrix 只有在退出码为 0 且 score/metrics 都存在时才计为 completed；
- 失败时保留 stdout/stderr tail，不能只看中间 artifact。

### 4.2 空生成物编译造成 strict-ready 假阳性

原 readiness 已添加 `no MMIO register accesses` blocker，但 harness/bare-metal ready 的布尔公式没有合取 `has_register_access`。空 RIS 生成出的 C 很容易编译并产生 0-op trace，因此可能同时出现“有 blocker”和“backend ready=true”。

修复后，`has_register_access` 是 harness、bare-metal 和 Linux 三个 strict gate 的共同必要条件。新增测试证明：即使三个 backend 都编译，零寄存器访问仍全部 strict-unready。

### 4.3 `strict_complete` 不能脱离识别范围解释

7 个 `no_register_access` 案例的 access accounting 都显示 `strict_complete=true`，因为识别集合为空且内部没有遗漏。这是 scoped accounting 的正确集合语义，但不是整个驱动语义完整。

结论是：可靠性报告必须同时读 `source_accesses`、`has_register_access` 和 blocker；单独引用 `strict_complete=true` 会夸大能力。

### 4.4 跨架构 libclang header diagnostics

ARM context 会暴露 target-specific inline asm diagnostics，例如宿主 libclang 对 ARM register constraint 的处理差异。当前 readiness 只统计目标源文件的 clang error，header diagnostics 保留在 warning provenance 中。SDHCI 的目标诊断仍单独形成 `clang_diagnostics` blocker，不能用 header filtering 隐藏。

## 5. 大模型工程能力边界

这次工作说明模型能够组织跨架构 Kbuild、构造 provenance 检查、实现机器矩阵，并在看到异常分布后追到 pipeline 与 readiness 的跨层根因。但也暴露了两个典型风险：

1. 首轮实现把 `analysis.json` 存在等同于 pipeline 完成，只有检查退出码和缺失 score 才发现错误；
2. 如果只看“12/12 backend compile”，模型很容易把空 RIS 的可编译 stub 当成泛化成功。

因此模型适合提出机制、实现验证器并迭代定位问题，但完成判定必须由负面 gate、artifact 完整性、退出码、语义覆盖和机器聚类共同约束。对 `no_register_access` 的后续修复还需要 subsystem-specific oracle；模型不能从编译成功自行证明 GPIO、SDHCI 或 virtio 的真实设备语义。

## 6. 下一阶段建议

下一阶段应先对 7-driver 聚类做机制分解，而不是逐驱动加特例：

1. 把调用路径分成 direct MMIO、regmap/opaque access、subsystem library access 和消息/queue I/O；
2. 为 GPIO generic helpers、SDHCI ops wrapper、virtio config/queue access建立带 provenance 的 library summary；
3. 要求 summary 从 callback type、callee identity、resource binding 和参数流触发，禁止按 driver 名触发；
4. 为每类机制选择至少一个正例、一个负例和 mutation test；
5. 只有 source access、RIS、生成代码与 oracle 同时闭环后，才提升 strict readiness。
