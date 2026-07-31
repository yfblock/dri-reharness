# C12: portable GPIO callback execution oracle

## 1. 目标

C11 从 typed `gpio_generic_chip_config` 合成了 7 类 GPIO callback，但 harness 与 bare-metal 只编译这些函数，没有执行证据，因此 zero-shot strict readiness 为 H=3/12、B=3/12、Linux=5/12。C12 的目标是建立由公开 subsystem contract 驱动的 runner，将 H/B 提升到 5/12，同时不放行仍有独立 blocker 的案例。

## 2. Contract-driven plan

runner 只选择满足以下条件的 module：

- callback table 为 `gpio_chip.get/get_multiple/set/set_multiple/direction_input/direction_output/get_direction`；
- 每个 leaf op 的 evidence 都来自 `linux.gpio_generic_chip_config` summary；
- access domain 为受支持的 MMIO，地址为 Symbolic 或 Fixed；
- 不含未证明循环。

选择逻辑不读取 driver name、source basename 或私有前缀。`set` 分别以 value=1 和 value=0 执行，其他 callback 使用固定的 offset、mask 和 bits，从而形成 8 次调用、7 个独立 callback module。

## 3. 两个后端

Harness 使用 byte-addressable fake MMIO，支持 native 与 big-endian 的 8/16/32-bit accessor。probe 后重新填充确定性字节模式，再执行 callback runner并输出逐 callback marker。

Bare-metal 正常产物仍使用 freestanding volatile MMIO。仅在定义 `REHARNESS_BAREMETAL_ORACLE` 时启用宿主 fake MMIO、trace 和 `main()`，因此同一份生成代码既保留部署形态，又可在 CI 中真实执行。

## 4. 独立 oracle

`verification/subsystem_callback_oracle.py` 不执行生成代码中的断言，而是独立解释 Formal RIS：

- 初始化与生成 runner 相同的确定性 byte memory；
- 解释 Const、Var、BinOp、Ite、Bits、Cond、Read、Write 和 RMW；
- 根据 width 和 summary evidence 处理 native/big-endian byte order；
- 对每个 marker 精确比较 operation kind、offset 和 value；
- 禁止缺少 callback、额外 callback 或部分覆盖冒充完成。

mutation test 将 TS4800 一个生成访问从 output register 改到 direction register，oracle 必须失败。negative control 使用同一 config 类型但不调用 `gpio_generic_chip_init`，不得生成 runner。

## 5. 结果

| 指标 | C11 | C12 |
|---|---:|---:|
| tests | 100 | 101 |
| zero-shot harness strict-ready | 3/12 | 5/12 |
| zero-shot bare-metal strict-ready | 3/12 | 5/12 |
| zero-shot Linux strict-ready | 5/12 | 5/12 |
| 主矩阵 harness strict-ready | 2/19 | 6/19 |
| 主矩阵 bare-metal strict-ready | 2/19 | 6/19 |
| 主矩阵 Linux strict-ready | 7/19 | 7/19 |

新增三个后端共同 strict-ready 的案例是 `gpio-ts4800` 和 `gpio-ge`。TS4800 验证 16-bit MMIO；GE 的 `GPIO_GENERIC_BIG_ENDIAN_BYTE_ORDER` 被 lowering 为 BE accessor 并通过值级 oracle。

DW APB 的 7/7 callback oracle 同样通过，但 40 个 unsafe computed address 和 2 个 conservative loop 继续阻塞。CLPS711x 的 config variant 保持 Unsupported，SDHCI synthetic accessor 也不被 GPIO runner 错误覆盖。zero-shot 首个公共 blocker 因此转为 `conservative_loop`，覆盖 3/12。

## 6. 能力边界

该 oracle 证明的是“Formal RIS callback contract 与两个通用后端生成物一致”，并覆盖 width、endianness、参数和寄存器值变换。它仍不是完整 Linux gpio-mmio library 的并发等价证明：library 内部 spinlock、shadow `sdata/sdir`、pinctrl delegation 与所有 flag 组合尚未进入 portable state model。未知或未支持 flags 会保持 unsupported，而不会仅因 runner 可编译就提升 readiness。
