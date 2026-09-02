# v2 论文量化审查报告

> 审查对象：`research/paper/v2/`（正文数值宏取自 `research/paper/generated_results.tex`）。
> 方法：论文中每一个量化声明逐条对照仓库版本化产物（`examples/`、`research/experiments/results/*.json`、`.ris` accounting）核数。
> 审查日期：基于当前工作树（分支 `arch-cleanup`，含未提交修改）。

## 0. 已核实一致的数字（供放心）

| 论文声明 | 核对结果 |
|---|---|
| DW 源码 1,844 行 | ✓ 1060(core)+476(mmio)+308(h) |
| 生成 Linux 828 / 裸机 581 / Rust 276 行 | ✓ 687+141 / 510+71 / 276 |
| DW 提取 28 模块、244 有证据操作 | ✓ `.ris` 28 个 module、244 个唯一 `@op_N` |
| dwc2 445 函数、726 调用边 | ✓ multisource-matrix.json |
| 626 函数、578 传播边、223/223 跨 TU | ✓ 92+89+445；54+79+445 |
| 表 3 全部行 | ✓ 与 multisource-matrix.json 逐字段一致 |

## P0 — 证据链断裂（动摇 RQ5，必须先修）

### P0-1 QEMU 结果当前不可再生，且宏生成器已崩溃

- 论文/宏声称：edu `EDU_TRACE_OK`、ftgpio `TRACE_MATCH_OK`，覆盖 6/6、7/7、13/13、8/8。
- 当前 `research/experiments/results/qemu.json`（2026-08-24 生成，`reharness_commit: 49018ef`，出自 `.worktrees/v2-academic-figures`）：两个实验 **`probe: false`、`trace_oracle: false`**。
- `tools/reporting/generate_paper_results.py:41-42` 读 `qemu_experiments["gpio-ftgpio010"]` 与 `edu_qemu["value_oracle"]` —— 对当前 qemu.json **直接 KeyError 崩溃**（键名 `ftgpio010` 无前缀、无 `value_oracle` 字段，schema 已漂移）。
- 结论：论文 RQ5 的两个 QEMU 数字目前**无法从仓库再生**；generated_results.tex 里是旧数据。需要查明 8/24 那次运行为何全 false（环境/内核/插桩），并同步 generator 与 qemu.json 的 schema。

### P0-2 「18 项检查清单」没有任何版本化产物

- 全仓库检索不到 18 项清单的定义（无 checklist 文件、无逐项检查脚本；`examples/dw-apb-ssi/` 只有生成物）。
- 这是论文中 **LLM 端到端翻译的唯一验收证据**（§6.5），却是全文唯一没有 artifact 落地的量化声明：评审无法核对清单内容、逐项结果与判定标准。

## P1 — 选择性量化 / 分母缺失

### P1-1 dwc2 的 68 个未解析调用：数据有，论文不给数

- 论文："the dwc2 case still has unresolved calls and diagnostics"（无数字）。
- multisource-matrix.json：`unresolved_internal_calls: 68`（dwc2，726 条边中 9.4%）；全语料 974 条边总体解析率 **93.0%**。
- 论文只报了 223/223=100%（跨 TU 边），对 68 个未解析的同模块内调用只字不给数。**选择性报 100%** 是审稿人最容易抓的点。

### P1-2 RQ5 与严格就绪的分母/名单缺失

- QEMU 只跑了 2 个实验（qemu.json 仅 edu、ftgpio 两项）：论文未说明"仅在 2 个驱动上尝试"及选择依据——读者无法区分"2/2 通过"与"2/19 通过"。
- 表 1/2 仅展示 5/19 驱动，**子集选择标准未说明**。
- 严格就绪 4/4/2 未点名驱动。实际名单（matrix.json）：harness/baremetal = {edu, gpio-ftgpio010, gpio-idt3243x, gpio-pl061}，Linux = {gpio-ftgpio010, gpio-idt3243x}。表 2 里 edu 行的 harness/baremetal 就绪、pl061 的就绪均不可见。

### P1-3 synthesis-eligible 5/19 是"死指标"

- 定义了 LLM 合成资格检查，但没有任何实验在这 5 个驱动上运行 LLM 路径（DW 案例不在 19 驱动语料内）。指标无下游消费者。要么补实验，要么删除。

### P1-4 zero-shot 12 例冻结数据完全闲置

- `zero-shot-matrix.json`：12/12 三后端编译、harness/baremetal strict 7/12、Linux 5/12、all 5/12、11/12 含硬件交互。
- 这是论文泛化主张（冻结 holdout + 反特化 guard）最有力的量化证据，v2 正文只字未提。若刻意收敛 scope，也应在论文中说明该数据存在及未纳入的理由。

## P2 — 口径不一致 / 呈现缺陷

### P2-1 %Sym 分母混用，合计行不自洽

- 子集行分母=全部 ops（如 virtio 46/59=78.0%）；合计行分母=可寻址 ops（366/471=77.7%）。
- 合计行 Ops=485 ≠ Sym+Fixed+Comp=471，表内不能自洽，仅正文口头解释。

### P2-2 `\MultiSourceOps`(4446) 被误当 dwc2 单模块数（正文数字错误）

- 4446 = 158+38+4250（三模块总和）；dwc2 实为 4250（表 3 自己的数字）。正文"produces 4,446 operations"应改为 4,250 或改述总和。

### P2-3 启发式分数无扣分分解

- edu DevSpec 0.688、pl061 0.938、virtio FuncSpec 0.875 —— 为什么扣分没有任何分解。RIS/FuncSpec/DevSpec 三列对读者信息量≈0：要么给出扣分构成，要么从主表移除（免责声明已有，但表仍在消耗版面与信任）。

### P2-4 耗时口径失真 + 现成数据未用

- 论文："Parsing kernel translation units dominates runtime (typically 10–30 seconds each)"。
- matrix.json 实测：19 驱动单驱动 **6.0–11.8s，中位 9.6s** —— 整体低于论文区间。且无硬件配置说明。
- 多源管线总耗时（28.5s / 40.9s / 176.5s）就在 multisource-matrix.json 的 `seconds` 字段里，论文未报。

### P2-5 零成本可用的量化数据被浪费

- `.ris` 的 `accounting`（DW：source_accesses 45 / emitted 45 / unaccounted 0）、`path_validation`（Z3：104 可满足、0 不可行、1 刻意不可达）。
- multisource 的 `propagation_amplification`（1.47/1.88/3.72）、`mmio_primitive_coverage=1.0`。
- 这些都是版本化、机器可读的证据，可直接强化 §4/§6 论证。

## P3 — 应有计数但完全缺失

1. IR `(function, offset)` 合并**碰撞次数**：论文承认可能碰撞，但语料中实际发生多少次没有任何统计。
2. wrapper 摘要推断的接受/拒绝计数（"reduces misclassification" 无数字）。
3. 修复循环实际轮数：DW 案例第几轮通过？first-pass 率？（EXPERIMENT_DEBT 已承认，但 DW 单案例的轮数是现成可记的。）
4. QEMU trace oracle 的子序列匹配**放过了多少额外访问**（容忍度未量化，读者无法判断检查强度）。
5. 严格就绪的 blocker 分类计数（matrix.json `readiness.blockers` 有逐驱动列表，可聚合成一张"阻塞原因分布"小表，直接解释 2–4/19 的差距来源）。

## 建议修复顺序

1. **修 QEMU 复现链**：重跑 `./run.sh qemu-experiments` 拿到 true 结果；同步 `generate_paper_results.py` 与 qemu.json 的 schema。不修则 RQ5 撼动。
2. **落地 18 项清单**：写成版本化 checklist 文件 + 逐项判定脚本，随 DW 产物入库。
3. **补分母与点名**：报 68/93.0%、点名 strict-ready 驱动、说明表 1/2 子集选择标准与"QEMU 仅尝试 2 例"。
4. **改正文数字**：4446→4250（§6.4）。
5. **换真实耗时**：6.0–11.8s（中位 9.6s）+ 多源 28.5–176.5s + 硬件说明。
6. **决策 zero-shot**：入正文（推荐，最强泛化证据）或在 limitation 中说明存在与不用的理由。
7. **删或补 synthesis-eligible**；删或分解启发式分数列。


## 修复状态（2026-08-30 更新）

| # | 问题 | 状态 |
|---|---|---|
| P0-1 | QEMU 复现链断裂 | **已修复**（2026-08-30）：规则式发射器从 8a96a8d 恢复为 `src/generator/rules/`（约 5.3k 行，经 `REHARNESS_GENERATION=rules` 显式启用）；修复 6 处新旧 IR 偏差（状态表达式净化、fops 撞名、canonical_args 遮蔽、normalize_module_ops 导入、锚点标签 unused、registrar 身份穿透）；instrument_mmio 仅对含 MMIO 函数注入 [rhfn]；套件 build/extract/trace 失败改为记录后继续；qemu.json 写入 value_oracle+四级覆盖。复跑结果：edu probe/trace/value 全过（EDU_TRACE_OK），ftgpio probe 过 + TRACE_MATCH_OK + 覆盖 7/7 6/6 13/13 8/8，与论文声明一致。**注意（2026-09-02）**：langgraph 分支已删除规则发射器（LLM-only），论文 §6.4/§6.5/摘要已改为"frozen baseline recorded in versioned artifacts"表述，不再声称树内可复跑规则发射 |
| P0-2 | 18 项清单无 artifact | **已落地**：`qa/verification/dw_apb_ssi_checklist.py` + `research/experiments/results/dw-apb-ssi-checklist.json`。诚实结果 9/18（编译 4 项与 Rust 数据流 5 项为真实未关闭失败），论文 §6.5 与摘要已改为如实描述 |
| P1-1 | dwc2 68 未解析调用不给数 | **已修复**：正文报 68 与 93.0%（新宏） |
| P1-2 | 分母/名单缺失 | **已修复**：表 1/2 子集标准写入 caption/正文；strict-ready 驱动点名（新宏 ReadyDriverList）；QEMU 分母声明"仅尝试 2 例" |
| P1-3 | synthesis-eligible 死指标 | 未动（需作者决策：补实验或删除） |
| P1-4 | zero-shot 数据闲置 | **已缓解**：§7.3 增补冻结 holdout 数据段（12/12 编译、strict 7/7/5）；是否升级为主评估由作者决策 |
| P2-1 | %Sym 分母混用 | **已修复**：表 1 caption 明确合计行分母口径 |
| P2-2 | 4446 vs 4250 | **已修复**：正文改用 \MultiSourceDwcTwoOps(4250)，总和另述 |
| P2-3 | 启发式分数无分解 | 未动（建议作者决策） |
| P2-4 | 耗时口径失真 | **已修复**：改用实测 6.0–11.8s（中位 9.6s）+ 多源 28.5–176.5s（新宏） |
| P2-5 | 现成量化数据浪费 | **已修复**（2026-09-02）：§6.5 DW IR 提取段补齐 accounting（45 处 MMIO 全核算、0 unaccounted、strict_complete）、path_validation（Z3 104 可满足/0 不可行/1 刻意 unreachable）、IR 分析（103 ops/0 missing/100% 覆盖）三组数字，全部来自 dw_spi.ris 版本化 artifact |
| P3 | 碰撞计数/修复轮数等 | 未动（需新实验，属 EXPERIMENT_DEBT） |

新宏（generated_results.tex，全部机器生成）：\MultiSourceDwcTwoOps、\EvalSecondsMin/Median/Max、\MultiSourceDwcTwoSeconds、\MultiSourceUnresolvedCalls、\MultiSourceCallResolutionPct、\HarnessReadyDriverList/\BaremetalReadyDriverList/\LinuxReadyDriverList、\ZeroShot* 系列。

## 修复状态（2026-09-02 严谨性复查）

| 位置 | 修改 |
|---|---|
| 摘要 | checklist 表述与 artifact 对齐：chip-select/interrupt/config 全过、4 项严格编译 + 5 项 Rust 数据流如实报为 open failures（\DWChecklistPassed/18）；QEMU 数字补 provenance 锚（manifest 摘要 + 源哈希 + 内核镜像 SHA-256） |
| §6.2 | 删除过时 `pi_synth.sh` 机制引用，改为"任意 OpenAI 兼容端点 + LangChain 客户端"；补全被截断的 virtio_mmio 句子 |
| §6.4 | baseline 表述改为"frozen rule-based baseline recorded in versioned matrix artifact"，消除与 LLM-only 现状的矛盾 |
| §6.5 | QEMU 段冻结 commit 锚定（156146f，kernel SHA-256 + manifest digests）；DW 四后端段逐项与 dw-apb-ssi-checklist.json 对齐（9/18，编译 4 项失败原因逐项写明：-Werror unused、Kbuild Error 2、Rust crate 不构建） |
| 宏生成器 | 修复 \GlueRatioChart 域错误（行数混入 0–100 百分比轴导致 Dimension too large）与图例 `&` 未转义；新增 \DWChecklistPassed/Total/CompileFailed/RustDataflowFailed |
| 排版 | Overfull \hbox 21→18，最差 29.7pt→6.3pt（路径改 \path、tt 长词重组、不可断连字符改写） |
