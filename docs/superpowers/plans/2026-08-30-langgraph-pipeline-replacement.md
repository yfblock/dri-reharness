# LangGraph Pipeline 替代实现计划（交接文档）

> **交接说明：** 本文档面向执行 Agent，自洽且可执行。执行前必读 Part A（现状报告）与 Part D（硬约束）；任何与 Part D 冲突的实现决策都必须停下询问，不得自行变通。

**Goal:** 将 `run_project_pipeline` 黑盒节点展开为 LangGraph 子图（experiment 修复环 + generation 流水线），在**行为逐项等价**的前提下获得细粒度 checkpoint（断点续跑）、阶段级可观测性与 backend/oracle 并行能力。

**Non-goals:**
- 不重写 extractor、oracle、LLM bridge 等领域组件（只做编排层搬运）
- 不修改现有 `qa/tests/` 任何断言（只允许新增测试文件）
- 不在本变更集内翻转默认后端（默认保持 `legacy`，翻转是独立的收尾任务，需对拍证据）

**Architecture:** 新增 `PipelineState`（JSON 可序列化）与两张子图（`experiment_graph`、`generation_graph`），通过特性开关 `REHARNESS_PIPELINE_BACKEND=graph|legacy` 与现路径并存；adapter 沿用 `experiment_protocol.py` 的 7 个 Protocol，验收/修复语义（`FailureClass`/`Feedback.retryable`/`IterationLimits`）直接复用，禁止重实现。

**Tech Stack:** Python 3.12, LangGraph >=1.2,<2.0（已 pin，不新增依赖）, SqliteSaver checkpointer, pytest。

---

## Part A — 现状实现报告

### A.1 编排层（保留不动）

`src/langgraph_workflow/graph.py::build_graph()`（L54）：6 节点线性图 + 一个条件边：

```
START → normalize_input → discover_driver_files → analyze_driver_files
      → build_pipeline_plan --(route_pipeline)--> run_project_pipeline | finalize
run_project_pipeline → finalize → END
```

状态 `WorkflowState`（`state.py`）全 JSON。本计划把 `run_project_pipeline` 节点替换为按 mode 路由的子图入口；`finalize` 的状态机**保持不变**（它消费 `pipeline_result` 的 `accepted/status/failure` 契约）。

### A.2 黑盒内部：`run_existing_pipeline`（`tools.py` L459）

| mode | 委托目标 | 规模 |
|---|---|---|
| `generation` | `src/driver_pipeline.py::run_driver_pipeline`（L49，491 行） | 5 oracle + 3 backend 串行循环 + `cc` 子进程 + 数十个产物文件 |
| `experiment` | `src/experiment_runner.py::ExperimentRunner.run`（L175，428 行） | `while True` 修复环 + 6 处 `continue` 修复点 |
| `analysis` | 直接返回 `analysis_only` | 无 |

### A.3 experiment 修复环语义（必须逐条保真，见 C1）

驱动代码：`experiment_runner.py` L228–L394。环序：`verify_contract → (linux: register_check) → compile → baseline_run → candidate_run → compare → accepted`。

计数器与限额（`experiment_manifest.py` L485 `IterationLimits`）：`compile/runtime/trace/total`，其中 `total` 可为 `None`。

每类失败的精确处理（路由函数规范，直接翻译自现有代码）：

| 失败点 | record 阶段名 | INFRASTRUCTURE | INCONCLUSIVE | 非 retryable | 限额字段 | 成功归零 |
|---|---|---|---|---|---|---|
| `verify_contract` 失败 | `contract` | —（按普通处理） | — | stop(failed) | `compile` | `contract_attempts=0` |
| linux 注册契约失败 | `contract` | 同上 | — | stop(failed) | `compile`（独立 `registration_attempts`） | 仅注册通过后 `registration_attempts=0`，**普通 contract 通过不重置它**（有专项测试钉死） |
| `compile` 失败 | `compile` | stop(failed) | — | stop(failed) | `compile` | `compile_attempts=0` |
| `baseline_run` 失败 | `baseline` | stop(failed) | stop(**inconclusive**) | stop(failed) | `runtime` | `runtime_attempts=0` 在 **candidate** 通过后 |
| `candidate_run` 失败 | `candidate` | stop(failed) | stop(**inconclusive**) | stop(failed) | `runtime` | 同上 |
| `compare` 不等 | `compare` | stop(failed) | — | stop(failed) | `trace` | `trace_attempts=0` |

共同规则：
- 环顶先 `used += 1`，`total is not None and used > total` → record(`repair`, failed, "total iteration limit exhausted") 并 stop
- 各失败点在限额未满且 retryable 时调用 `repair`（`_repair` L395，走 PiBridge，带 feedback + 旧 candidate）；repair 失败即 stop(failed)
- `record(stage, used, status, payload, feedback)` 产生 `StageRecord`（`experiment_protocol.py` L44，字段 `stage/iteration/status/manifest_digest/evidence_digest/payload`），**顺序即执行序**，append-only，逐条持久化到 `iterations/NN-<stage>.json`

### A.4 generation 流水线语义

`driver_pipeline.py` L49 起：`build_generation_contract` + readiness → 落盘基础产物 → 5 个 source oracle（gpio-mmio / sdhci / virtio / w1c / transaction-ir）→ `for backend in (harness, baremetal, linux)`：generate → lowering → lowering-plan → ast_leaf（harness/baremetal）/ linux_registration_ast（linux）→ `cc` 编译执行 + trace 子序列比对 → 汇总 `gr/results` → 写 `verify/*.json`。

产物路径（`<outdir>/generated/<backend>/…`、`<outdir>/verify/*.json`、`<outdir>/<name>.formal.json` 等）与内容被下游 digest/对齐校验消费（`tools.py::_artifact_digest`、`_verify_experiment_source_alignment`）。

### A.5 行为钉子（黄金测试，禁止改断言）

- `qa/tests/test_experiment_runner.py`（13 个测试）：`test_stage_order_and_append_only_records`、`test_linux_registration_retry_limit_is_not_reset_by_general_contract_pass`、`test_exhausted_limit_is_rejected`、`test_extraction_and_infrastructure_fail_closed`、`test_non_retryable_*`、`test_unexpected_adapter_exception_is_infrastructure_failure`、`test_contract_verifier_runs_before_compile_and_fails_closed`、`test_linux_compile_is_followed_by_registration_contract_gate` 等
- `qa/tests/test_langgraph_workflow.py`（29 个测试）：workflow 层协议与 fail-closed 语义

### A.6 目标拓扑图

`docs/langgraph-topology-proposed.svg`（本仓库，已渲染验证）。现状对照图：`docs/langgraph-topology.svg`。

---

## Part B — 目标设计

### B.1 模块布局（全部为新增文件）

| 文件 | 职责 |
|---|---|
| `src/langgraph_workflow/pipeline_state.py` | `PipelineState(TypedDict)`：candidate / scenario / evidence / compiled_ref / attempts 计数器 / records / status 等，全 JSON |
| `src/langgraph_workflow/experiment_graph.py` | `build_experiment_graph(*, adapters, checkpointer=None)`：修复环子图 |
| `src/langgraph_workflow/generation_graph.py` | `build_generation_graph()`：generation 子图（Send fan-out） |
| `src/langgraph_workflow/pipeline_entry.py` | mode 路由入口 + 特性开关读取 |
| `qa/tests/test_experiment_graph.py` | 子图行为测试 + 影子对拍 |
| `qa/tests/test_generation_graph.py` | generation 子图测试 |
| `qa/verification/shadow_compare.py` | 新旧实现对拍 harness（Task 0 核心） |

### B.2 experiment 子图拓扑（与 A.3 表格一一对应）

```
prepare(load manifest/对齐/extract/synthesize)
  → verify_contract → [linux? register_check : bypass] → compile
  → baseline_run → candidate_run → compare → ACCEPTED(finalize)
路由函数 route_after_*（读 attempts/limits/failure_class）:
  失败 → repair → verify_contract（唯一回边）
  INFRASTRUCTURE/非retryable/限额耗尽 → finalize(failed)
  baseline|candidate INCONCLUSIVE → finalize(inconclusive)
```

- 修复环节点内调用注入的 adapter（Protocol 签名不变），**复用** `_feedback()`/`_coerce()`/`_invoke()` 的异常→failure_class 归类逻辑（可 import，不得复制粘贴重写）
- `records` 在 state 中以 `StageRecord.to_dict()` 列表累积（reducer: append）；`_persist` 的 `iterations/NN-<stage>.json` 落盘节奏由对应节点完成，保证中断恢复后文件序号连续

### B.3 adapter 边界 JSON 化（本计划主要工作量所在）

- state 只存 JSON；adapter 返回值在节点边界规范化：candidate 已是 Mapping（原样）；`compiled.value` 须转换为 `{paths: [...], metadata: {...}}` 引用（真实 compiler 落盘返回路径）；runtime/comparator 返回 trace 文本路径 + 摘要
- 无法 JSON 化的值（二进制/句柄）一律落盘后传路径——**禁止**把活对象塞进 state
- 测试 fake adapters 本就返回 JSON 值，直接可用

### B.4 generation 子图

`extract → contract → oracles(Send×5, reducer 汇聚) → backends(Send×3) → verify_backend → compile_and_trace → write_artifacts → finalize`。并行 join 语义：**任一 backend 的 generation 阶段异常 = 整体 failed**（与现状串行首次异常即停等价）；oracle 结果 reducer 逐键合并。注意：3 backend 并行写 `verify/` 需按 backend 分文件（现状即 `<backend>-*.json`，天然无冲突，但 `analysis.json` 等共享文件只允许 write_artifacts 单节点写）。

### B.5 特性开关

`REHARNESS_PIPELINE_BACKEND`（默认 `legacy`）：`pipeline_entry.py` 读取；`graph` 走子图，`legacy` 走 `run_existing_pipeline`。对外 JSON 结果契约（`accepted/status/output_dir/records/failure/comparison`）两种后端完全一致。

---

## Part C — 实施计划（按序执行，每 Task 独立可合入）

### Task 0 — 影子对拍基建（规模 M，最优先）

**Files:** 创建 `qa/verification/shadow_compare.py`、`qa/tests/test_shadow_compare.py`

- [ ] Step 1: harness 接收 `(manifest, fake_adapters)`，分别用 `ExperimentRunner.run`（legacy）与 `build_experiment_graph().invoke`（graph，空实现时先跑通骨架）执行，deep-compare：`ExperimentResult.status/accepted/failure/comparison` + `records` 逐项（`to_dict()` 列表 deep-equal，含顺序）
- [ ] Step 2: 用 `test_experiment_runner.py` 同款 fake adapters（确定性、离线）构造 ≥5 个场景：正常 accepted、contract 修复后通过、compile 限额耗尽、baseline INCONCLUSIVE、linux 注册限额（复现 `test_linux_registration_retry_limit_is_not_reset...` 场景）
- [ ] Step 3: graph 侧未实现时 harness 输出明确的 MISSING 后端标记（不是假绿）

**验收：** `PYTHONPATH=src:qa:qa/verification python3 -m pytest -q qa/tests/test_shadow_compare.py` 收集通过（对拍场景 XFAIL/SKIP 标注 graph 未实现）。

### Task 1 — experiment 修复环子图（规模 L）

**Files:** 创建 `pipeline_state.py`、`experiment_graph.py`、`test_experiment_graph.py`

- [ ] Step 1: 定义 `PipelineState`（含 `used/contract_attempts/registration_attempts/compile_attempts/runtime_attempts/trace_attempts/records/candidate/scenario/status/...`）
- [ ] Step 2: 实现 8 个节点（prepare/verify_contract/register_check/compile/baseline_run/candidate_run/compare/repair）+ finalize；失败语义按 A.3 表格逐条实现路由函数；INFRASTRUCTURE/INCONCLUSIVE/retryable 归类复用 `experiment_protocol` + runner 的既有函数
- [ ] Step 3: `records` append reducer；`iterations/NN-<stage>.json` 落盘节点与 legacy 逐字节一致
- [ ] Step 4: 新增图专属测试（每类失败 × 限额边界 × linux/非linux 绕过），全部离线 fake
- [ ] Step 5: 打开 Task 0 harness，5 个影子场景全部 records 逐项相等

**验收：** `PYTHONPATH=src:qa:qa/verification python3 -m pytest -q qa/tests/test_experiment_graph.py qa/tests/test_shadow_compare.py` 全绿；legacy 测试 `test_experiment_runner.py` 仍全绿（未被触碰）。

### Task 2 — 断点续跑与 interrupt（规模 S）

**Files:** 修改 `experiment_graph.py`、新增测试

- [ ] Step 1: `SqliteSaver` checkpointer 挂载；验证在 `compile` 节点后中断 → 换一个会成功的 fake compiler → `invoke(None, config)` 续跑至 accepted，且 `records` 序号连续、不重复 extract/synthesize
- [ ] Step 2: `interrupt_after=["verify_contract"]` 冒烟（可选能力，不进默认路径）

**验收：** 新增续跑测试通过；checkpoint 文件可跨进程重新加载。

### Task 3 — generation 子图（规模 L）

**Files:** 创建 `generation_graph.py`、`test_generation_graph.py`

- [ ] Step 1: oracle/backend 两处 `Send` fan-out + reducer；join 语义按 B.4
- [ ] Step 2: 产物逐字节对拍：同一 driver 源分别跑 `run_driver_pipeline`（legacy）与子图，`diff -r` 两棵产物树 + digest 相等
- [ ] Step 3: 3 backend 并行与串行结果一致性测试

**验收：** 新测试全绿 + 产物树逐字节一致。

### Task 4 — 接入主 workflow（规模 M）

**Files:** 修改 `src/langgraph_workflow/graph.py`、`tools.py`、新增 `pipeline_entry.py`、`test_langgraph_workflow.py` **只增不改**

- [ ] Step 1: `build_pipeline_plan` 的条件边改为三路：`finalize` / generation 子图入口 / experiment 子图入口（`route_pipeline` 返回值扩为三值）
- [ ] Step 2: 子图结果投影回 `pipeline_result`（`accepted/status/output_dir/records/failure/comparison`），`finalize` 状态机零改动
- [ ] Step 3: 开关默认 `legacy`；`REHARNESS_PIPELINE_BACKEND=graph` 时 workflow 端到端走子图（用 fake pipeline 服务测试）
- [ ] Step 4: `test_langgraph_workflow.py` 新增开关相关用例（不得修改既有 29 个用例）

**验收：** 全量 `qa/tests` 绿；`graph` 模式端到端测试绿。

### Task 5 — 翻转默认与收尾（规模 S，独立 PR，需明确批准）

- [ ] Step 1: 影子对拍在 ≥3 个真实 driver × legacy/graph 各一次，records 与产物树全部相等，证据贴入本文件末尾
- [ ] Step 2: 默认切 `graph`，legacy 保留一个发布周期后删除
- [ ] Step 3: 更新 `README.md` / `REPRO.md` 中 pipeline 执行说明与拓扑图引用

---

## Part D — 硬约束（违反任何一条 = 变更被拒绝）

- **C1 行为等价**：新路径的 `StageRecord` 序列（内容+顺序）、`status/accepted/failure/comparison` 必须与 legacy 在同输入同 fake adapter 下逐项相等（Task 0 harness 仲裁）。语义翻译以 A.3 表格为准，禁止"合理化"任何差异（如合并计数器、放宽归零时机）。
- **C2 产物契约**：generation 成功运行的产物树与 legacy 逐字节一致（路径、内容、digest）。节点边界崩溃后的中间状态允许与 legacy 不同。
- **C3 序列化边界**：`PipelineState` 所有字段 JSON 可序列化；checkpointer 必须可用 `SqliteSaver` 完整 round-trip。活对象/句柄/子进程引用入 state = 违规。
- **C4 adapter 协议不变**：`experiment_protocol.py` 的 7 个 Protocol、`AdapterResult`、`Feedback/FailureClass` 归类逻辑（含 retryable 推导）原样复用；禁止重实现失败分类。
- **C5 禁改清单**：`src/extractor/**`、`src/driver_pipeline.py`（行为）、`src/experiment_runner.py`（行为）、`src/experiment_manifest.py`（schema）、`qa/tests/` 既有断言。以上只允许"新增"不改"既有"。
- **C6 离线确定性**：新测试禁止网络、禁止 `langchain_openai`、禁止真实 QEMU/`cc` 依赖（compile/runtime 用 fake adapter）；固定随机性。
- **C7 依赖不变**：不新增第三方依赖；`requirements-langgraph.txt` 的 pin 不动；Python 3.12 语法兼容。
- **C8 开关默认 legacy**：`REHARNESS_PIPELINE_BACKEND` 缺省值必须是 `legacy`；翻默认仅限 Task 5 且需对拍证据与人工批准。
- **C9 渐进合入**：Task 0→1→2→3→4 顺序执行，每个 Task 结束时全量 `qa/tests` 绿；禁止跨 Task 携带未完成的半成品（如 graph 路径默认启用）。
- **C10 落盘纪律**：experiment 的 `iterations/*.json` 与最终 `manifest.json`、generation 的产物写入只发生在对应节点；禁止在路由函数/reducer 内做 IO。
- **C11 并发语义显式化**：任何 Send fan-out 必须定义单分支失败的聚合行为并有测试覆盖（generation 按 B.4：任一 generation 异常 = 整体 failed）。
- **C12 文档同步**：拓扑变更必须回写 `docs/langgraph-topology-proposed.svg` 引用说明；`finalize` 契约变更绝对禁止（它是外层 workflow 与 CLI 的公共协议）。

## Part E — 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 修复环语义漂移 | Task 0 对拍 harness 先于一切图代码存在 | 开关切回 `legacy`（零代码回滚） |
| 序列化往返失真 | C3 round-trip 测试；真实 adapter 落盘传路径 | 同上 |
| 并行写冲突 | B.4 共享文件单节点写 | Send 改回串行 map |
| langgraph API 演进 | pin 不动；子图不暴露框架类型给外层 | legacy 路径独立存活 |

## 附：关键代码索引

| 位置 | 内容 |
|---|---|
| `src/langgraph_workflow/graph.py` L54/L250 | build_graph / run_workflow |
| `src/langgraph_workflow/tools.py` L459/L466/L516 | run_existing_pipeline / generation 分支 / experiment 分支 |
| `src/experiment_runner.py` L175/L228–394/L395 | run / 修复环 / _repair |
| `src/experiment_protocol.py` L9/L44 | FailureClass / StageRecord |
| `src/experiment_manifest.py` L485 | IterationLimits |
| `src/driver_pipeline.py` L49 | run_driver_pipeline |
| `qa/tests/test_experiment_runner.py` | 13 个语义钉子（禁改） |
