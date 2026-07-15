# Zero-shot generalization foundation v1

## 1. 目标和冻结协议

本阶段不继续针对现有 19-driver 调整 readiness，而是建立可审计的零样本泛化基础：

1. 在首次 extractor 运行前冻结 holdout；
2. 禁止为 holdout 增加 driver-name/private-prefix 特例；
3. 从 Kbuild 恢复真实 translation-unit compile context；
4. 用冻结后的首个新驱动做 importer 前后对照；
5. 保留语义 blocker，不以 neutral fallback 或放宽 readiness 美化结果。

冻结文件是 `drivers/holdout/zero-shot-v1.json`，包含 12 个驱动、三档难度、Linux commit、source SHA-256、首个运行案例和禁止出现在核心实现中的标识符。选取阶段检查了文件存在性、subsystem、规模和 Kbuild context 可用性，但没有在冻结前运行 extractor。

`verification/check_generalization_guard.py` 校验：

- Linux submodule commit 未漂移；
- 每个 holdout source SHA 未变化；
- first-run case 仍在冻结集合中；
- extractor/ 和 generator/ 中不存在 holdout 专用标识符。
- source basename/device-name 条件和 private-MMIO wrapper 表没有超出冻结 specialization allowlist。

`./run.sh test` 在回归测试之前执行该 guard。

## 2. Kbuild compile-context importer

新增 `extractor/compile_context.py`，context 查找顺序为：

1. CLI `--compile-commands`；
2. `REHARNESS_COMPILE_COMMANDS`；
3. kernel build 根目录的 `compile_commands.json`；
4. source 对应 object 的 Kbuild `.cmd`；
5. auto 模式下才退回原有 include guess。

支持三种模式：

- `off`：明确禁用，仅用于基线对照；
- `auto`：找到真实 context 就使用，否则记录 fallback；
- `required`：找不到 context 直接失败。

importer 不把整个 GCC command 原样传给 libclang。它只保留 preprocessing/language 相关参数，例如 include、forced include、define、undefine、language standard、目标位宽和少量 type-layout flag；dependency、optimization、warning、objtool 和 GCC-only code-generation flag 会被丢弃。所有相对 include 路径都相对于原 Kbuild cwd 转为绝对路径。

analysis metadata 记录 context origin、provenance、directory、sanitized arguments、argument SHA、raw command SHA，以及 libclang compatibility override 后的 effective argument SHA。extraction cache identity 也包含 compile database/`.cmd` 的 mtime 和 size，防止上下文变化后返回旧结果。AST 与 SVF bitcode 使用同一 context。

## 3. 首个冻结驱动结果

首个案例由 manifest 固定为 `gpio-altera`，source 为固定 Linux submodule 中的 `drivers/gpio/gpio-altera.c`。

importer-off 与 required 对照结果：

- functions analyzed：13 / 13；
- RIS operations：18 / 18；
- recognized source accesses：18 / 18，strict accounting；
- RIS SHA-256：一致；
- DeviceSpec SHA-256：一致；
- harness、bare-metal、Linux：两侧均编译；
- target-source clang errors：0 / 0；
- required provenance：`kernel/build/drivers/gpio/.gpio-altera.o.cmd`。

真实 Kbuild context 包含 33 个 sanitized parser arguments，其中包括 `-nostdinc`、真实 generated include、`MODULE`、`KBUILD_BASENAME` 和 `KBUILD_MODNAME`。它没有改变已经正确提取的 RIS，证明 importer 对该案例没有造成语义回退。

该驱动仍非 strict-ready：

- edge IRQ handler 中存在保守 polling loop；
- Linux backend 仍有 source-private/lifecycle unsupported binding。

因此本阶段证明的是“零样本 context 导入与语义稳定”，不是“新驱动已完整翻译”。

## 4. 泛化过程中遇到的问题

### 4.1 Kbuild command 不能直接交给 libclang

`.cmd` 包含大量 GCC code-generation 参数，如 retpoline、mcount、stack protector、objtool 和 dependency generation。直接使用会被不同版本的 clang 拒绝，或把与 AST 无关的宿主配置耦合进解析。

解决方式是建立明确的 parser-relevant allowlist，而不是不断追加单个报错 flag 的 blacklist。能力边界是：当前 importer 恢复 preprocessing/type context，不声称复现 GCC code generation。

### 4.2 相对 include 必须以 Kbuild cwd 为基准

`.cmd` 同时包含 Linux source 的绝对 include 和 build tree 的 `./include`、`./arch/.../generated`。libclang API 没有为每个 TU 自动切换 cwd；若直接传入，相对路径会相对于 reharness cwd 解析。

解决方式是在导入时把所有 path-bearing flag 绝对化，并记录原 directory。

### 4.3 精确的 `MODULE` context 暴露 synthetic function

首次 required run 将 `module_init/module_exit` 展开的 `__inittest` 和 `__exittest` 识别为目标文件函数，functions analyzed 从 13 变为 15。RIS 没变化，但 inventory 被 kernel macro implementation 污染。

修复按通用 kernel registration helper 过滤这两个 synthetic declaration，没有引用 holdout driver 名称。零样本验收增加了 function inventory stable gate。

### 4.4 真实 context 不会自动消除所有 diagnostics

gpio-altera 源码把 `int *` 传给期望 `u32 *` 的 property API，libclang 仍报告两条 severity-2 target-source diagnostic。它们不是缺 include/Kconfig 导致的 error，也不会被 importer 合理消除。

这说明“使用真实 Kbuild context”和“clang 无任何告警”是不同目标。当前 gate 只要求 target-source error 为 0，同时保留 warning provenance。

### 4.5 `.cmd` 只覆盖实际构建过的 object

冻结 12 个驱动中，只有当前内核配置实际构建的 object 天然拥有 `.cmd`。对其他 architecture/Kconfig 驱动，auto 会退回 guess，required 会失败。

下一步需要为 holdout 生成对应 arch/Kconfig build 或 compile database，不能把 fallback 结果冒充 exact Kbuild context。

### 4.6 Context 完整不等于语义完整

gpio-altera 在 importer 前后都能完整 accounting 18 个访问并编译，但仍被 loop proof 和 Linux lifecycle 阻塞。compile context 解决的是 frontend fidelity，不解决 private-state ownership、polling semantics 或 subsystem lifecycle。

这是本阶段最重要的负面结论：不能因为解析更精确，就把 strict readiness 自动提升。

### 4.7 测试环境没有独立 pytest 命令

环境中没有 `pytest` executable。新增测试先通过直接调用测试函数验证，最终仍由仓库自带 standalone runner 执行，结果为 88/88。项目不应把外部 pytest CLI 当作唯一 CI 入口。

## 5. 下一步

1. 为其余 holdout 生成真实 compile database，并报告 context coverage；
2. 禁止新增 basename/Kconfig 常量特例，逐步删除现有 `tu.py` 特例；
3. 将 source-private object/state ownership 与 lifecycle 建模作为下一项机制工作；
4. 对 holdout 按 near/medium/far 分层报告 compile、strict、fallback 和人工语义包成本；
5. 每个新增 strict-ready 案例继续要求 differential/mutation 证据。
