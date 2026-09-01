# 双周工作报告（2026-08-12 — 2026-08-26）

**项目**：ReHarness — LLM 驱动的设备驱动程序跨平台翻译框架
**分支**：`langgraph`
**周期产出**：21 次提交（+5,879 / −2,362 行），另有约 96 个文件、+15,600 行改动已完成待分批提交；论文 v2 初稿（约 1,300 行 LaTeX，11 节，已编译出 PDF）。

---

## 一、工作概述

本周期完成了系统从「单一 SPI 示例驱动的一次性翻译管线」向「多子系统、多驱动的通用翻译框架」的架构升级。核心工作分四条主线：

1. **编排与 LLM 后端重构**：引入 LangGraph 状态机编排，用 LangChain 替换原 Pi Agent 桥接层；
2. **通用驱动翻译框架**：Profile 插件化 + 子系统契约 + Linux 注册契约，覆盖 9 种总线/子系统；
3. **验证体系建设**：QEMU 实验协议规范化、19 个子系统原生测试、静态 Oracle 体系扩容；
4. **论文 v2 修订**：完成初稿全部 11 节的撰写并编译通过。

---

## 二、主要完成工作

### 2.1 编排与 LLM 后端重构（8/12、8/24）

- **统一 LLM 后端**（8/12）：后端统一为 Pi Agent，引入项目级配置（`.reharness/pi/models.json`），支持多模型切换。
- **LangChain 替换 Pi Agent**（8/24，计划 22/22 步全部完成）：
  - 新增 `src/langchain_bridge.py`，重写 `src/generator/llm_bridge.py`（+152 行），改进请求构造、响应归一化与失败重试的不变量；
  - 配套 `test_langchain_bridge.py`、`test_pi_bridge_protocol.py` 等协议级测试。
- **LangGraph 工作流**（8/24，计划 12/12 步全部完成）：
  - 新增 `src/langgraph_workflow/`，将「分析 → 生成 → 实验」拆分为可编排节点，替换原 `driver_pipeline.py`（−440 行，已删除）；
  - 新增 `src/auto_driver.py` 端到端自动入口，实现零人工介入的完整翻译流程。

### 2.2 通用驱动翻译框架（8/25）

- **静态抽取器增强**（`src/extractor/`，约 +3,000 行）：
  - `call_graph.py`（+455）、`dataflow.py`（+409）、`spec_infer.py`（+324）、`wrappers.py`（+317）、`formalize.py`（+256）；
  - 支持跨翻译单元调用边解析（多源矩阵实测：974 条调用边、223 条跨 TU 边全部解析）、指针/别名传播、RMW 合并、事务 IR 提取。
- **Profile 插件化**（计划 16/17 步完成，收尾中）：
  - 定义插件契约与来源（provenance）校验，新增通用驱动 Profile 注册表（`feat: add generic driver profile registry`）；
  - 建立 `benchmarks/profile-catalog.json`、`driver-profile-definitions.json`、`subsystem-providers.json`、`profile-templates/` 目录体系。
- **子系统与注册契约**：
  - 新增 `subsystem_contracts.py`、`subsystem_providers.py`、`subsystem_contract_verification.py`、`linux_registration_contracts.py`；
  - 重写生成器 prompt（Linux 后端 +216 行），针对新契约体系适配。

### 2.3 验证体系建设（贯穿全周期，约 +7,500 行）

- **QEMU 实验协议**：新增 `qemu_experiment_protocol.py`，规范实验执行与三态判定（`accepted` / `failed` / `inconclusive`）。
- **子系统原生测试 ×19**（新增，C 语言）：覆盖 GPIO v1/v2 兼容层、I2C（含 i2cdev）、MDIO、SPI、USB、virtio 队列、network、AMBA 生命周期等。
- **设备注册器**：新增 amba / i2c / mdio / spi 设备注册器 C 实现，配合既有 pci / platform 注册器。
- **静态 Oracle 扩容**：Linux 注册 AST Oracle 重写（+524 行）、事务 IR Oracle、backend lowering plan Oracle。
- **可复现性**：新增 `deterministic_llm.py` 确定性 LLM 桩，保证实验矩阵可离线复现；新增 `run_profile_matrix.py`、`run_auto_driver.py` 矩阵运行器。

### 2.4 实验结果与论文（8/17 规划、8/24–26 落地）

- **论文 v2 初稿完成**：`research/paper/v2/` 共 11 节约 1,300 行 LaTeX，已编译出 PDF；确定「受限驱动翻译（constrained translation）」的论文定位与会议论文结构。
- **学术图表方案确定并产出架构图**（`docs/diagrams/`）。

---

## 三、关键数据指标

### 3.1 翻译成功率

| 实验批次 | 范围 | 结果 | 成功率 |
|---|---|---|---|
| Profile 矩阵（final） | 9 种总线/子系统 profile（pci、platform、amba、i2c、mdio、network、spi、usb、virtio） | 全部 accepted，子系统测试全过（GPIO 9 项、I2C 4 项、USB 3 项等） | **9/9 = 100%** |
| 自动驱动编排（auto-driver） | edu（PCI）、ftgpio010（platform），零人工介入 | edu：EDU_TRACE_OK、probe=10、oops=0；ftgpio010：9/9 GPIO 子系统测试通过 | **2/2 = 100%** |
| 早期研究批次 | edu、ftgpio010 | edu 通过；ftgpio010 报「子系统语义测试失败」 | 1/2 = 50% |
| 零样本 v1（真实上游驱动） | 12 个真实驱动（clk、gpio、sdhci 等） | 管线完成 12/12，全后端编译 12/12，严格就绪 5/12 | 42% |
| 零样本 v2 | 同上 12 个 | 全后端编译 10/12，严格就绪 0/12（blocker 聚类：linux_semantic_binding） | 0%（根因已定位） |
| 静态抽取可靠性 | 19 个真实驱动、385 个 MMIO 访问 | 严格可靠 5/19，不支持访问/控制流 10 + 6 处 | 26% |

**进展亮点**：ftgpio010 从早期的「语义测试失败」修复到 auto-driver 全过，验证了新框架的端到端有效性。

### 3.2 多源静态抽取能力（multisource-matrix）

3 驱动 / 19 翻译单元 / 27,447 行源码：4,446 个操作、3,794 个 RIS MMIO 操作、223 条跨 TU 调用边 100% 解析、68 个寄存器、959 处 RMW。

---

## 四、系统架构（现状）

```
驱动源码 + Profile 注册表
   → 静态抽取器 (libclang: ast_model → call_graph → dataflow → mmio → wrappers → spec_infer → formalize)
   → ⟨产出⟩ RIS 操作序列 · DeviceSpec · 证据
   → LangGraph 编排 (挂 LangChain LLM 桥 + 子系统/注册契约层)
   → 四后端生成 (linux 内核模块 / baremetal C / rust_baremetal / harness)
   → 验证 (静态 Oracle ×3 · profile_runtime · 矩阵运行器 · deterministic_llm)
   → QEMU 运行时 (设备注册器 ×5 总线 + 子系统原生测试 ×19)
   → 判定 accepted/failed/inconclusive → artifacts → 论文
```

现代版矢量架构图：`docs/diagrams/architecture-modern.svg`（Mermaid 版：`docs/diagrams/architecture.svg`）。

---

## 五、遗留问题与风险

1. **未提交改动体量大**：约 96 个文件、+15,600 行改动滞留工作区（涉及 `src/`、`qa/`、`examples/`、实验产物），需尽快分批整理提交，避免成果悬空。计划勾选状态（如通用翻译框架 0/43）也需同步更新。
2. **真实驱动（零样本）仍是主要瓶颈**：静态抽取严格可靠率仅 26%；零样本 v2 全部卡在 linux_semantic_binding 同一 blocker 上——这正是通用翻译框架后续任务的目标对象。
3. **Profile 插件运行时计划差 1 步收尾**；测试源覆盖计划差 1 步。

---

## 六、下阶段计划与时间估算

按当前「设计先行 + 逐任务勾选」的节奏（单日可完成 12–22 个计划步骤）：

| 序号 | 工作项 | 预估工时 |
|---|---|---|
| 1 | 工作区改动分批提交固化 + 计划勾选同步 | 0.5 天 |
| 2 | 通用驱动翻译框架收尾（实现已过半，计划 43 步） | 1–2 天 |
| 3 | 通用注册根（计划 20 步，设计已完成） | 1 天 |
| 4 | USB profile 运行时（计划 16 步，设计已完成） | 1 天 |
| 5 | 自动驱动编排扩展（计划 21 步，设计已完成） | 1 天 |
| 6 | 开发文档计划（文档索引 / 用户 runbook / 架构指南） | 1 天 |
| 7 | 论文 v2 修订（图表、实验数据回填、润色） | 3–5 天 |
| | **合计** | **约 9–12 个工作日（2–2.5 周）** |

**推进顺序建议**：先固化现有成果（项 1），再按 2 → 3 → 4 → 5 推进工程侧，最后集中完成论文修订（项 7）——论文依赖前序实验产物，放最后可引用最新数据。

---

*报告生成日期：2026-08-26。数据来源：git log（8/12–8/26）、`artifacts/profile-matrix-final/matrix.json`、`artifacts/auto-driver/`、`research/experiments/results/`（reliability / zero-shot / multisource 矩阵）。*
