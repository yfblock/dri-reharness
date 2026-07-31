# Codex 工程代理 v5→v6 实测复盘：oracle、泛化边界与 readiness 假阳性

> - 范围：从 `paper-artifact-v5` 继续，建立 Highbank 算术 oracle，以 Visconti PLL 检验 clock source-private 泛化边界，并用 gpio-sodaville 将 strict readiness 从 6/19 提升到 7/19。
> - 实现提交：`7ab0cf2 feat: validate arithmetic and reach seven strict-ready drivers`。
> - 权威证据：`experiments/results/matrix.json`、`multisource-matrix.json`、`clock-model-boundary.json`、`qemu.json`。

## 1. 最终结果

- 测试：58 passed, 0 failed。
- 19-driver：harness、bare-metal、Linux 均 19/19 编译。
- strict readiness：三个后端均为 7/19；新增项是 `gpio-sodaville`。
- 提取聚合：425 ops、314 symbolic、62 fixed、35 computed、71 RMW。
- Highbank：22 个算术基线用例通过；PLL divq、A9 bus shift、periclk increment 三类 mutation 全部被检出。
- Visconti PLL：保守拒绝，原因显式包含 `pll_base`、`rate_table/rate_count`、`lock` 和未绑定 private value。
- 多源：223/223 跨 TU 调用边继续全部解析，三个案例三后端与 original Kbuild 均成功；USB modpost warning retry 仍记录为 `strict_success=false`。
- QEMU：edu 值级 oracle 与 gpio-ftgpio010 trace oracle 再次通过。

## 2. 过程中遇到的实际问题

### 2.1 续接摘要给出的工作目录不等于真实 Git root

外层工作区 `/home/yfblock/Code/dri-trans-paper` 含一个只读占位 `.git` 目录，但真实仓库位于 `reharness/`。第一次 `git status` 返回：

```text
fatal: not a git repository (or any of the parent directories): .git
```

必须重新枚举目录和嵌套 `.git`，不能因为环境上下文或上一模型摘要给出了 cwd 就跳过 repo-root audit。

### 2.2 readiness gate 一度制造了语义假阳性

初始矩阵已经显示 `gpio-sodaville` 三后端 strict-ready，生成物也没有 `REHARNESS_UNSUPPORTED`。如果只看 gate，可以直接宣布 7/19 完成。但逐项检查生成 C 后发现：

- PCI ID 仍是 fallback `0xffff:0xffff`，而原驱动是 `0x8086:0x2e67`；
- `ngpio` 仍是默认 32，而原驱动是 12；
- 只保留了 `irq_set_type`，丢失 `GPIO_INT` mask/unmask、`GPSTR` EOI 和 `handle_fasteoi_irq`；
- 更隐蔽的是，原驱动通过 `gpio_generic_chip_init()` 获得 get/set/direction 操作，生成的 `gpio_chip` 却没有这些 callback。

这说明“blockers 为空”只证明当前 gate 没看到问题，不证明框架 helper 隐含的语义已恢复。此次最重要的能力边界不是模型不会写代码，而是模型和指标都容易围绕已知 blocker 形成共同盲区。

### 2.3 第一个看似最精确的修复无法通过目标构建

最初方案是在生成模块中直接复用 `gpio_generic_chip_init()`，这在源码层最接近原驱动。但固定实验内核的 out-of-tree `Module.symvers` 没有该导出，modpost 报告：

```text
ERROR: modpost: "gpio_generic_chip_init" [gpio_sodaville.ko] undefined!
```

随后改为从已识别的 native-endian 32-bit `dat/set/dirout` 配置生成等价 GPIO callback，并显式维护 data/direction shadow 与 spinlock。这个失败说明 Linux API 是否存在于源码、是否声明在 header、是否可被当前模块链接，是三个不同问题；模型记忆或源码相似度不能替代固定内核 Kbuild。

### 2.4 具体样本实现差点被过度推广

初版 generic GPIO analyzer 会接受带 `flags`、`clr` 或 `dirin` 的配置，但 emitter 实际只实现 Sodaville 使用的 32-bit native-endian `dat/set/dirout` 语义。如果不做末次审计，未来驱动可能被错误地套用相近但不等价的模型。

最终将接受域收紧为：

- `sz == 4`；
- 必须存在 `dat`、`set`、`dirout`；
- 不接受 `clr`、`dirin`；
- 不接受非零 flags。

这与 Visconti 负例表达同一个原则：保守拒绝比“看起来能编译”的泛化更重要。

### 2.5 默认测试工具与项目实际入口不一致

模型再次尝试 `python3 -m pytest`，环境没有 pytest。读取 `run.sh` 后改用项目自带 standalone runner，最终得到 58/58。常见工程惯例可以作为猜测起点，不能作为执行事实。

### 2.6 长任务工具存在双层异步状态

测试和矩阵先返回 cell ID，再暴露底层 session ID；多次 polling 没有输出，因为 Python runner 缓冲到结束才打印。如果把“wait cell 完成”误认成“子进程完成”，会过早宣布成功。

最终只以底层进程 `exit_code=0` 和完整的 `58 passed, 0 failed`、矩阵逐驱动输出为证据。

### 2.7 结果必须在实现提交之后重新生成

第一次 matrix、boundary 和 QEMU 运行发生在 dirty tree，JSON 中 `reharness_commit` 仍是旧 HEAD。为避免冻结一个无法由 commit 单独复现的状态，流程改为：

1. 先提交实现；
2. 在实现提交上重跑全部机器结果；
3. 再提交结果、文档和论文；
4. 最后创建 artifact tag。

这是实验制品管理中容易被忽略的时序约束。

## 3. 大模型表现较好的方面

### 3.1 能从“已经通过”的结果中继续寻找反证

在矩阵已显示 7/19 时，模型没有立即停止，而是检查 PCI ID、ngpio 和 IRQ lifecycle，继而发现 generic GPIO callback 也缺失。这种 completion audit 比单纯消除报错更有研究价值。

### 3.2 能构造正向 oracle 和反向 mutation

Highbank 验证不是只断言生成文本包含某个公式，而是编译生成 callback，在独立 MMIO shim 中执行，与 Python reference 对比，并要求三类有意错误公式被测试抓获。Mutation test 提供了“测试确实对关键公式敏感”的反证。

### 3.3 愿意保存负面泛化结论

Visconti 没有被中性化为可编译代码后宣称支持；分析器输出具体 private-state 拒绝原因。模型能够在有明确验收标准时保留“当前不支持”的结果。

### 3.4 能跨源码、facts、生成物和内核构建定位根因

PCI vendor 宏来自 kernel header，device ID 与 ngpio 来自本地 define，GPIO 行为隐藏在 framework helper，IRQ lifecycle 隐藏在对 `irq_chip_type` 字段的赋值。修复要求同时阅读这些层，而不是只修改 readiness 规则。

## 4. 大模型暴露出的能力边界

### 4.1 容易把指标通过当成任务完成

上一阶段已经把 Sodaville 计为 strict-ready，但缺少关键框架语义。若用户没有要求“先分析思考清楚”并指定中等难度对照，模型很可能以 gate 数字结束任务。

因此模型的可靠边界取决于验收函数是否覆盖目标语义。模型可以优化给定指标，也会继承指标盲区。

### 4.2 容易把具体 lowering 扩展成模式

面对相似的 `gpio_generic_chip_config`，模型倾向于先写一个“通用”解析器，再在审计时补拒绝条件。对 C framework idiom，这种过度推广尤其危险，因为一个 flags 位就可能改变读写、方向或 endian 语义。

### 4.3 编译仍不是语义等价证明

Sodaville 现在有源码结构断言和固定内核 Kbuild，但没有真实 Sodaville 硬件或等价 QEMU device model。Highbank 有算术 oracle，但没有真实时钟硬件。当前结论是“恢复了被 oracle/结构测试覆盖的语义”，不是完整硬件等价。

### 4.4 验证器本身需要被验证

Highbank mutation test 说明 oracle 对三类公式错误敏感；如果没有 mutation，只看到 22/22 通过，reference 与实现可能共享同一错误。对 Sodaville，目前仍缺少运行时 mutation/oracle，证据强度低于可执行设备模型。

### 4.5 代码规模和长期架构仍需人工评审

本阶段在 generator 中加入 source parser、GPIO callback emitter 和 IRQ lifecycle emitter。测试与 Kbuild 能验证当前行为，但不能证明这是长期最简架构，也不能替代对 FormalRIS 是否应承载更多 framework state 的设计评审。

## 5. 能力边界分级

| 工作类型 | 本次表现 | 必要条件 | 主要边界 |
|---|---|---|---|
| 仓库续接与状态恢复 | 中等 | 必须重新确认 Git root/HEAD/dirty tree | 环境摘要可能指向外层工作区 |
| 跨层根因定位 | 较强 | 源码、facts、生成物、Kbuild 可同时检查 | 只看 blocker 会遗漏 helper 隐含语义 |
| 算术 oracle / mutation 设计 | 较强 | 可独立执行生成 callback 和 reference | 覆盖的公式不等于覆盖硬件行为 |
| Linux framework API 实现 | 中等 | 固定版本真实 Kbuild | header 存在不代表模块可链接 |
| 模式泛化 | 中等偏弱 | 必须有明确接受域和负例 | 容易先泛化、后补拒绝条件 |
| 语义完整性判断 | 弱到中等 | completion audit + runtime/formal oracle | readiness gate 会形成共同盲区 |
| 实验制品冻结 | 较强 | 实现提交后重跑、JSON commit 审计、tag | 时序错误会冻结 dirty-tree 结果 |

## 6. 后续评估建议

1. 每个 readiness 提升都要求列出 framework helper 隐含的 callback、资源规模、ID 和 teardown lifecycle，而不仅是 blocker 消失。
2. 每个新 source pattern 必须同时提供接受样本和至少一个拒绝样本；对 flags/endian/width 变体做 mutation 或 fixture。
3. oracle 除了正向用例，还必须包含 mutation sensitivity；否则不能证明测试能抓住目标错误。
4. 将 agent run manifest 机器化：记录起止 commit、命令、退出码、失败分类、结果文件和未证明声明。
5. 下一步若继续提升 readiness，优先选择有可执行设备模型或可构造 reference oracle 的驱动，而不是只追求数字。

## 7. 结论

本阶段说明，大模型作为工程代理不仅能消除显式 blocker，也能在被要求做真实性审计时发现 gate 的假阳性，并构造算术 oracle、mutation test 和负面泛化边界。

但最关键的反面事实是：模型曾经已经“完成”7/19，而真实 PCI/GPIO/IRQ 语义仍有缺口。可靠性来自源码逐项审计、固定内核 Kbuild、mutation、负例和 commit-aware 冻结流程，而不是来自模型自信或 readiness 数字本身。
