# 大模型工程代理能力边界：zero-shot 12/12 与 DW APB multi-bank 实测复盘

> 范围：SDHCI/virtio 完成后的 DW APB multi-bank GPIO/IRQ 生命周期、全量回归、矩阵与制品刷新。

## 1. 本阶段完成的机制

- 从源码恢复 bank selector、`reg`/`ngpios` 属性、bank 上限、IRQ-capable bank 和 parent IRQ 获取方式；
- Linux 后端改为 parent device state 加每-bank `gpio_chip`、selector、data/direction shadow，而不是并发 callback 共用一个 `gpio_bank_index`；
- 只为源码证明的 bank 建立 IRQ domain、parent IRQ ownership 和 chained dispatch；
- 从源码结构证明标准 `irq_chip` bit 操作后，重建 ack、mask、unmask、enable、disable 和 trigger type 语义；
- DW APB oracle 同时覆盖 PM trace、bank addressing、Linux lifecycle 和 IRQ value/type lowering，13 个 mutation 全部被检出；
- zero-shot 12 个案例的 harness、bare-metal、Linux 编译与当前 strict gate 均达到 12/12；
- 110 个测试、19-driver matrix、3 个 multi-source module、reliability 和两项 QEMU 实验重新执行。

## 2. 过程中真实出现的问题

### 2.1 交接摘要很有用，但不能作为当前事实

交接摘要正确指出 DW APB Linux multi-bank 是最后一个已知 blocker，也保留了 dirty tree 和论文外部改动信息。但摘要中的“其余回归已修复”和预期矩阵数字仍必须重跑验证。实际完整测试连续发现三个陈旧断言：静态 loop guard、SDHCI source-private write accessor、virtio subsystem-state。后继模型若只按摘要继续写代码，会把“预计通过”误报为“已经通过”。

### 2.2 指标达到 12/12 后仍存在 IRQ value 盲区

首版 multi-bank 实现通过 Linux Kbuild、PM oracle、bank lifecycle structural oracle 和当时的 zero-shot gate。但生成的 IRQ callback 仍把局部 `val` 写回原值：ack 写 0，mask/unmask 缺少 bit transform，`set_type` 缺少真实 switch 更新。原因是 MMIO helper 内联后，读取与调用者局部赋值之间的标量关系没有自动重建。

这个问题说明：

- lifecycle 正确不代表 callback value 正确；
- blocker 为空不代表 oracle 覆盖了所有 callback；
- 聚合 readiness 会继承验证器的盲区。

最终处理不是删除 blocker，而是增加源码结构证明的 IRQ lowering，并加入 `irq_ack_value`、`irq_mask_transform`、`irq_type_semantics` mutation。当前结论仍应理解为这些已建模 contract 的严格就绪，而不是任意 GPIO IP 的完整硬件等价证明。

### 2.3 局部修复触发了 multi-source 生成回归

第一次重跑 multi-source matrix 时，ASPEED vHub 和 DWC2 从可编译退化为 N/N/N。具体根因不是一个：

- source-private address-of 被中性化后留下非法 `&&0` 与不完整二元表达式；
- function macro 已导出，但其大写依赖宏没有进入 fallback 集合；
- `Return` 表达式没有经过与普通 value 相同的 source-private normalization；
- 大延时统一 lowering 为 `udelay`，在固定内核上链接到 `__bad_udelay`；
- userspace harness 缺少 `likely/unlikely` 兼容宏。

这些错误说明大模型擅长快速修一个目标案例，但跨后端文本 lowering 存在隐含闭包：表达式、宏依赖、返回值、延时 API 和链接语义必须一起检查。单驱动测试无法替代 multi-source 全矩阵。

### 2.4 常见工具习惯不等于仓库事实

模型首先尝试了 `pytest`，环境实际没有安装；项目的权威入口是 `./run.sh test`。长测试又同时暴露 unified session 和 cell wait 两层异步状态，若把一次 wait 返回当成进程完成，会过早开始冲突任务或误报结果。最终判断必须来自完整退出状态和汇总行，例如 `110 passed, 0 failed`。

### 2.5 Clang diagnostics 可能是缺失 Kconfig context，而非源码错误

WMT GE 的三个 redefinition diagnostic 来自版本化单文件语料脱离原 Kbuild 后未定义 `CONFIG_FB_WMT_GE_ROPS`，导致 companion header 选择 disabled-feature inline stubs。恢复该源码原本的 enabling context 后，target-source clang error 从 3 降为 0；header noise 仍按既有规则单独记录。模型必须区分源码错误、header 噪声和编译上下文丢失。

## 3. 大模型表现较好的方面

- 能把 extractor metadata、生成 C、固定内核 Kbuild、Formal interpreter、source reference 和 mutation 串成一条证据链；
- 在矩阵回退后没有围绕结果 JSON“修数字”，而是读取具体编译日志并归因到五类生成问题；
- 能从单一 bank selector 的并发风险推导出 parent/per-bank ownership 结构；
- 能在发现 gate 盲区后主动收窄结论，并补充能证伪该机制的 mutation；
- 能维护长任务状态，最终重新生成 matrix、multi-source、reliability、QEMU 和论文宏。

## 4. 明显能力边界

- 模型不会天然知道 oracle 漏掉了什么；通常需要源码逐 callback 审计或异常生成物触发怀疑；
- 对跨文件隐含契约没有形式保证，一次看似通用的 normalization 很容易破坏远端 backend；
- 编译成功只证明类型/链接边界，不能证明寄存器值、并发、IRQ ordering 或 subsystem ownership；
- mutation 的质量决定证据强度；若 mutation 只改结构而不改值，仍可能漏过语义错误；
- 长上下文和交接摘要会诱导模型把“已知 blocker 已消除”误认为“目标语义已完整覆盖”。

## 5. 对后续评估的建议

1. 为每个 strict-ready subsystem 建立 coverage manifest，列出 callback、lifecycle、state、并发和错误回滚维度；
2. 同时保留 source differential、backend runtime 和结构 oracle，避免实现与解释器共享同一错误；
3. 每次修改通用 expression/control lowering 后必须跑 single-source、zero-shot 和 multi-source 三层矩阵；
4. 将“模型提出的完成判定”也视为待验证输出，要求机器结果、制品 SHA 和 clean-tree 审计；
5. 对没有设备级 oracle 的并发 IRQ、DMA 和 USB lifecycle，继续明确标为未证明，不用编译或 readiness 数字替代。

## 6. 结论

本阶段显示，大模型作为工程代理能够完成跨分析、生成、验证、文档和制品的长链路工作，也能在多个错误假设后根据证据收敛。最重要的正面能力是快速构造可执行的机制和反例；最重要的边界是它会与现有 gate 共享盲区。

可信度来自独立 source oracle、mutation、固定内核 Kbuild、全量矩阵、QEMU 和最终 Git 审计，而不是来自模型已经把数字推进到 12/12。
