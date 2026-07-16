# C11: subsystem library summaries

## 1. 目标

C10 的 12-driver zero-shot matrix 中有 7 个案例落入 `no_register_access`。C11 的目标不是按驱动补丁恢复数字，而是建立由公开 helper、callback table、typed config 和参数流触发的通用机制：

- GPIO generic helper/config；
- SDHCI logical accessor 与 `sdhci_ops`；
- virtio config space 与 virtqueue。

specialization guard 仍只允许历史上的两个 DWC2 private wrapper；新增机制没有 holdout driver name、basename 或私有前缀。

## 2. GPIO generic summary

触发条件是 `gpio_generic_chip_init(chip, &config)`，且第二个参数能解析为 `struct gpio_generic_chip_config` 局部对象。分析器从 compound initializer 或受控赋值中恢复：

- `sz`；
- `dat/set/clr`；
- `dirout/dirin`；
- `flags`。

summary 将 library init 的初始 data/direction read 加入调用者，并合成标准 `gpio_chip` callback：`get`、`get_multiple`、`set`、`set_multiple`、`direction_input`、`direction_output` 和 `get_direction`。每个操作保留 registration call site、config field、width、callback 和 `linux.gpio_generic_chip_config` contract provenance。

固定 config 可作为 MMIO 交给 Linux lowering。互斥选择 `dirin/dirout` 的 config 被标为 `gpio_generic_config_variant` unsupported domain，不会假装已经绑定 source-private variant state。

正例测试检查 7 个 callbacks、evidence 和寄存器映射；mutation 将 `set` offset 从 `0x04` 改到 `0x0c`，要求 summary 同步变化。负例使用同一 config 类型但调用无关 initializer，必须产生 0 个 synthetic function。

## 3. SDHCI summary

公开的 `sdhci_read{b,w,l}`、`sdhci_write{b,w,l}` 和 `sdhci_be32bs_*` 被建模为 `host->ioaddr + reg` 的 logical register access。它们位于独立的 subsystem layout 表，不进入 driver-private specialization inventory。

对 `struct sdhci_ops` initializer：

- target source 中定义的 wrapper 直接获得 read/write op 和 table role；
- 指向已知公开 accessor 的外部 read/write callback 被合成为 module；
- 其余外部 core callback 进入 `unmodeled_callbacks`，形成显式 `subsystem_summary` blocker。

因此 HLWD 的三种 read 与三种 delayed write 都可审计，但 `set_clock`、`set_bus_width`、`reset` 和 `set_uhs_signaling` 仍保守阻塞。NPCM 的 `sdhci_readl(..., SDHCI_CAPABILITIES)` 则直接恢复为一个 logical MMIO read。

## 4. Virtio summary

virtio 不应被伪装成设备 MMIO。分析器利用原始 macro spelling 恢复被 libclang 展开的 `virtio_cread_le/virtio_cwrite_le`，并区分：

- `virtio_config`：config read/write/byte stream；
- `virtqueue`：add/get/kick/detach/size。

这些操作进入 RIS、accounting 和 provenance，但 reliability 为 `Unsupported`，生成器输出显式 unsupported marker。virtqueue callback 与 `input_dev.event` 也获得具体 table role，不再表现为 missing-role/callback-binding 噪声。

## 5. 矩阵结果

| 指标 | C10 | C11 |
|---|---:|---:|
| `no_register_access` | 7/12 | 0/12 |
| exact context | 12/12 | 12/12 |
| 三后端 compile | 12/12 | 12/12 |
| harness strict-ready | 3/12 | 3/12 |
| bare-metal strict-ready | 3/12 | 3/12 |
| Linux strict-ready | 3/12 | 5/12 |

原 7 个案例当前 RIS operation 数为：TS4800 9、CLPS711x 13、DW APB 49、GE 9、NPCM 1、HLWD 6 个 register op（另有 3 个 delay）、virtio-input 43。

首个非 umbrella 公共 blocker 变为 `subsystem_validation`，覆盖 5 个驱动。它表示合成 callback 已进入 RIS/Linux lowering，但 generic harness/bare-metal 尚未执行这些 callback，不能用只运行 probe 的 trace 宣称 callback 语义已经验证。

主 19-driver 矩阵也因此更保守：469 ops、356 symbolic、74 fixed、25 computed、88 RMW、117 conditions、157 registers；三后端仍 19/19 编译，strict readiness 为 H=2/19、B=2/19、Linux=7/19。旧 H/B=6/19 有四个案例忽略了 generic GPIO library callbacks，因此不能继续保留。

## 6. 过程中遇到的问题

1. libclang 将 virtio macro 展开为 `set/get/__virtio_cread_many`，只看 callee name 会把普通 field call与 config access 混淆；必须同时要求原始 macro spelling。
2. 合成 `get_multiple/set_multiple` 后，Linux callback 的 pointer 参数与通用 backend 的标量抽象不同；直接把 `*mask/*bits` 写入 RIS会使 harness/bare-metal 失去类型正确性。最终保持 RIS 标量形式，仅在 Linux callback signature 中重绑定指针。
3. 初版 Linux generator 不支持 `get_multiple/set_multiple` callback signature，导致 4 个 GPIO holdout 的 Linux compile 回归；补齐签名、canonical args 和 probe binding 后恢复 12/12。
4. generic GPIO summary 同时影响现有 FTGPIO、Cadence、IDT3243x 和 Sodaville。若只重跑 zero-shot matrix，会留下主矩阵、论文和 QEMU 叙述不一致。
5. summary 使 FTGPIO probe 新增真实的 initial data/direction reads，旧文本 RIS parser 只识别行首 `R/W`，因此漏掉了 `value := R(...)`；旧的 4-op oracle 实际是解析假阴性，不能删除 summary 维持旧数字。
6. QEMU 脚本虽然编译了 GPIO exerciser，却没有传给 guest；同时 `--exercised probe` 的子串匹配误把 `probe__gpio_generic_*` 当成已执行 callback，并允许不同模块复用同一条全局 trace。修复后 extraction 额外输出结构化 Formal RIS JSON，instrumentation 记录精确 `[rhfn]` 边界，oracle 按 formal-module/runtime-function 调用序列逐段匹配。真实 gpiolib 路径通过 6/6 模块、7/7 调用、16/16 ops 和 7/7 寄存器偏移。

## 7. 大模型能力边界

模型能从 7 个表面相同的零操作结果中分离三种不同 subsystem 语义，并构造通用触发、negative control、mutation test 和矩阵聚类。但首版实现也出现了典型的跨后端遗漏：只验证 RIS 数字后，Linux pointer callback 签名、未接线的 guest exerciser、文本 parser 漏读和 trace 重复计数才在完整回归中暴露。

因此此类工作不能以“`no_register_access` 消失”为完成证据。至少需要同时检查 specialization guard、source accounting、callback binding、三个 backend compile、strict gate、主矩阵影响和 runtime oracle。

## 8. 下一步

1. 已在 C12 为合成 GPIO callbacks 建立 harness/bare-metal execution oracle，并只对 7/7 callback 全部通过的案例恢复 strict readiness；详见 `docs/gpio-callback-runner-c12.md`；
2. 对 DW APB 的 `gpio_reg_convert()` 建立纯 helper return summary，减少 40 个 unsafe computed address；
3. 建模常见 SDHCI core callbacks，并修复 NPCM/Dove clang diagnostics；
4. 为 virtio 引入 config/queue 原生事件代数和 backend，而不是长期借用 unsupported register op 表示。
