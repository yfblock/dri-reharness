# Agent 记忆和接续提示

这是后续 Agent 开始工作前必须读取的短规则。它不是模型的隐式记忆，而是仓库内
可审查的交接记录。

## 1. 当前上下文

- 仓库：`/home/yfblock/Code/dri-trans-paper/reharness`
- 当前工作分支：`langgraph`
- 当前日期基线：2026-08-26
- 项目目标：面向多种 Linux driver framework 的自动提取、生成、编译和验证框架。
- 默认 LLM backend：LangChain。
- 当前模型：`gpt-5.6-luna`。
- 当前 endpoint：`https://ai.yfblock.cn/v1`。
- 默认 profile acceptance：9 个 runtime-ready profile。
- `serdev-generic`：识别可用，runtime fixture 缺失，保持 inconclusive。

## 2. 开始任务前

1. 先执行 `git status --short` 和 `git branch --show-current`。
2. 读取本目录的 [README.md](README.md)、[开发记录](03-开发记录.md) 和与任务相关的
   [系统架构](02-系统架构.md)。
3. 检查用户已有修改。工作树很可能是 dirty 的，不能假设所有 diff 都属于当前任务。
4. 用 `rg` 查找现有实现和测试，优先复用 manifest、profile registry、provider 和
   runtime adapter，不要先写新的总线特判。
5. 明确任务是回答/诊断、文档更新还是代码修改。只有用户要求变更时才写代码。

## 3. Git 和文件安全

- 禁止使用 `git reset --hard`、`git checkout --` 或其他会抹除用户修改的命令。
- 不要删除、覆盖或清理不属于当前任务的 artifacts、submodule 修改或未跟踪文件。
- 使用 `apply_patch` 编辑文件，不用 shell 重定向或 Python 写文件。
- `vendor/linux` 是 Git submodule。AMBA compile-test patch 会使其保持 dirty；
  不要为了“清洁状态”擅自还原。
- 任何 commit、push、merge 或 branch cleanup 都必须得到明确请求；本任务只需修改文件。

## 4. 设计不变量

- generic runner 不按驱动名、源码 basename 或总线名加入行为分支。
- profile 行为通过 `benchmarks/driver-profile-definitions.json`、manifest template、
  provider catalog 和 `ProfilePlan` 表达。
- manifest 是 runtime policy 的边界，不能从日志、源码名或 QEMU 输出反推未声明能力。
- plugin profile 默认 explicit-only，不自动扩大默认 matrix acceptance 集合。
- registration definition、generated code、runtime registered object 和 callback probe
  是不同证据层，不能互相替代。
- subsystem provider 被声明不等于 provider 已运行成功；必须检查 guest marker 和
  structured test report。
- `accepted`、`failed`、`inconclusive` 三种状态有不同含义，缺证据必须保持
  `inconclusive`，不能转成 success。
- QEMU fixture 是代表性 contract，不是整个 Linux 子系统或真实硬件的完整仿真。

## 5. LLM 规则

- analysis 模式不调用模型，优先用它验证 extractor/evidence。
- generation/experiment 的模型输出必须经过 parse、generation contract、AST/
  registration、Kbuild、QEMU、subsystem 和 unload gate。
- 不要把 API key 写入 `.reharness/pi/models.json`、README、日志或 artifact。
- 先检查 `REHARNESS_LLM_MODEL`、`REHARNESS_LLM_BASE_URL`、
  `REHARNESS_LLM_API_KEY`、`REHARNESS_LLM_BACKEND` 的实际值。
- `ChatOpenAI` 的 Chat Completions 兼容性不能证明 Responses API 兼容性；涉及协议
  迁移时要读取当前 bridge 实现和实际响应结构，并增加独立测试。
- 修复循环必须保留每轮结构化错误，不要直接把模型的“已修复”文本当作证据。

## 6. 修改后的最低验证

根据风险选择验证范围，但至少包括：

```bash
git diff --check
bash -n <changed-shell-files>
PYTHONPATH=src:qa:qa/verification \
  python3 -m py_compile <changed-python-files>
```

profile/runtime 相关变更至少运行：

```bash
PYTHONPATH=src:qa:qa/verification \
pytest -q qa/tests/test_profile_runtime.py \
  qa/tests/test_profile_matrix.py \
  qa/tests/test_driver_profiles.py
```

若改变了 manifest、fixture、QEMU 或 profile acceptance，必须再运行对应单 profile
和完整 `profile-matrix`，并读取 `matrix.json` 与 raw `qemu.log`。没有新鲜输出，
不能在最终回答中说“通过”。

## 7. AMBA 接续提示

AMBA fixture 的两个关键前置依赖不能删除：

1. resource base 必须避开 guest PCI resource tree，当前是 `0x180000000`；
2. synthetic device 必须有 `apb_pclk` clkdev mapping，否则 AMBA core 在 candidate
   `.probe` 前返回 `-ENOENT`。

修改 AMBA 时优先查看：

```bash
rg -n "REHARNESS_AMBA|resource|EBUSY|ENOENT|probe|pclk" \
  artifacts/profile-matrix-final/amba-generic/qemu.log \
  qa/verification/device-registrar/amba-registrar.c \
  vendor/linux/drivers/amba/bus.c
```

## 8. 不要过度声称

以下说法需要额外证据，不能由当前 matrix 直接推出：

- “整个 Linux 子系统已经测试完成”；
- “所有 Linux 驱动类型都支持”；
- “LLM 翻译语义等价”；
- “Responses API 已经可用”；
- “所有 tests 都通过”；
- “serdev 已 runtime 验证”。

准确表述应包含输入、profile、fixture、测试来源、命令、artifact 和时间范围。

## 9. 推荐接续顺序

如果继续扩展通用 framework：

1. 先在 registration catalog 中定义 root table、identity 和 callback link；
2. 在 profile definition 中声明 evidence、capability 和 template；
3. 增加 repository-owned fixture 和 manifest-owned tests；
4. 先写 parser/profile/manifest focused tests；
5. 单独运行 Kbuild 和 QEMU；
6. 把结果加入 matrix 前检查它是否真的是 trusted runtime-ready；
7. 同步本目录的开发记录和当前状态。

如果继续修复失败：先读完整错误，复现，追踪数据流，提出单一假设，用最小变更验证，
不要连续堆叠猜测性补丁。
