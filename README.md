# reharness

reharness 从 Linux C 设备驱动中提取形式化寄存器交互序列（RIS），推断后端无关的设备语义，并确定性生成 userspace harness、bare-metal C 和 Linux 内核模块。

核心分析使用 libclang AST、过程间有限深度内联、流敏感数据流与污点追踪。相比正则基线，它能恢复宏寄存器偏移、包装函数中的 MMIO、分支条件、地址算术和 read-modify-write（RMW）变换。

## 当前状态

- 版本化语料：`benchmarks/drivers/baseline/` 内含 19 个单源测试驱动；`benchmarks/drivers/multisource/` 包含真实 Kbuild 多源模块 manifest。
- 版本化内核：`vendor/linux/` 是固定到实验 commit 的 Git submodule。
- 三个确定性后端：harness 19/19、bare-metal 19/19、Linux 18/19 可编译（Linux 仅 `sdhci-esdhc-mcf` 因 Coldfire 平台宏 `ESDHC_DEFAULT_QUIRKS` 未编译）；未编译项保留明确日志，不用 stub 成功替代。
- 严格语义 readiness：C19 冻结矩阵为 harness 4/19、bare-metal 4/19、Linux 0/19，三个后端共同 0/19。C20 新增 Linux required-subset AST 与 registration identity attestation，并在 lowering plan v3 中取交集；FTGPIO 定向正例达到 35/35 AST、35/35 registration 和 Linux strict，尚未据此重写完整 19-driver 冻结矩阵。DWC2 虽为 2023/2023 AST，registration 仅 62/2023，仍 strict false。
- 多源规模：C67X00（4 C）、ASPEED vHub（5 C）与 DWC2 dual-role（10 C），合计 19 TU / 27,447 LoC；三个后端均为 3/3 编译。C15 将 DWC2/ASPEED 的 unaccounted source site 从 48/4 降为 0，但 direct evidence frontier 仍显式阻塞 call-semantics strict 声明。
- 跨 TU 质量：974 条内部调用边，其中 223 条跨 TU 边全部解析；578 条调用边传播了 MMIO 摘要。
- 原始 MMIO 对照：907 个源码 primitive、1,091 个 direct AST 操作、C19 当前 3,794 个 RIS MMIO 操作（含为 lexical coverage 保留的 direct evidence frontier）。
- 测试套件：205 tests（15 repository-path + 143 core + 8 generated-C AST + 10 Linux registration AST + 21 lowering-plan + 1 C20 readiness + 2 read-provenance + 5 DeviceSpec JSON）；测试入口先执行冻结 holdout/specialization guard。
- 可靠性审计：每个 source site 与 RIS op 均带稳定证据；C15 机器报告给出 scoped strict 5/19。`whole_program_complete` 由 linked analysis、调用语义、CFG、路径、访问、值、循环和 evidence 等严格 gate 合取决定，不再是无条件常量。
- Clock 边界验证：Highbank 22 个算术 oracle 用例通过，三类公式 mutation 均被检出；Visconti PLL 因未绑定的 `pll_base`、rate table 和 lock state 被保守拒绝。
- QEMU：edu 通过值级 oracle；gpio-ftgpio010 通过结构化 Formal RIS、精确函数边界和真实 gpiolib exerciser 的 probe/callback MMIO oracle（6/6 模块、7/7 调用、13/13 ops、8/8 寄存器偏移）。
- C67X00 HPI：32/32 computed address 可安全 lowering；`hpi.base`、`hpi.regstep` 和 `sie_num` 显式建模。5 个 primitive、4 个原始 C↔RIS differential case 通过，4 类 mutation 全被检出。
- SVF 别名分析：off、auto、required，默认 off；多源 manifest 会先链接所有 TU bitcode，再执行一次 WPA，并记录 linked-bitcode SHA、工具版本和 source provenance。C67X00 required run 成功链接 4 TU。
- 零样本泛化基础：`benchmarks/drivers/holdout/zero-shot-v1.json` 冻结 12 个未用于实现的驱动；`src/extractor/` 或 `src/generator/` 出现这些驱动的专用标识会使 CI 失败。Kbuild importer 优先读取 `compile_commands.json`，否则自动读取对象对应的 `.cmd`，并把来源、参数与 SHA 写入 analysis metadata。
- Subsystem summaries：冻结矩阵中原先 7 个 `no_register_access` 已降为 0。GPIO 从 typed `gpio_generic_chip_config` 合成 callback；SDHCI accessor/ops table 与 virtio config/virtqueue 分域记录。zero-shot v1 仍为三后端编译 12/12；当前 gate 下 harness/bare-metal strict 为 7/12，Linux 为 5/12，三后端共同 strict 为 5/12。首个跨驱动 RIS blocker 仍是 5 个案例共有的 `call_context`，Linux 还叠加了未完成的 registration/callsite 证明。virtio config/virtqueue 被建模为 subsystem state，因此 12 个案例中 11 个含寄存器硬件交互，virtio-input 不伪装成 MMIO。

下表来自 C19 当前 19-driver 矩阵；AHCI direct evidence frontier 会增加真实未覆盖操作，因此计数与 C14 冻结结果不同：

| 驱动数 | Ops | Symbolic | Fixed | Computed | RMW | Conditions | Registers |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 19 | 485 | 366 | 64 | 41 | 73 | 123 | 157 |

地址分类是刻意分开的：只有可静态命名的访问记为 Symbolic；常量偏移和运行时索引分别保留为 Fixed 与 Computed，不会伪造成“100% symbolic”。

## Repository layout

- `src/`：extractor、generators 和 synthesis bundle 实现。
- `qa/`：自动化测试、独立 oracle、矩阵验证和 native trace tests。
- `benchmarks/`：baseline、zero-shot holdout 和 multi-source 驱动输入。
- `tools/pi/`：Pi coding-agent synthesizer 及其本地 Node 依赖。
- `research/`：论文、版本化实验结果、历史记录和 known-good artifacts。
- `platform/`：kernel build assets 和测试 root filesystems。
- `vendor/`：固定版本的第三方源码树。
- `artifacts/`：可重新生成的输出。

根目录只保留项目元数据、主要文档、规范功能目录和公开调度器
`run.sh`。内部脚本和 Python 模块不依赖根目录兼容链接。

## RIS 与语义输出

RIS 操作包括：

- Read：var := R(width, addr)
- Write：W(width, addr) = expr
- ReadModifyWrite：RMW(width, addr) = transform
- TransactionRead / TransactionWrite / TransactionUpdate：显式区分
  regmap、I2C/SMBus 和公共 MFD helper 的 target、selector 与 scalar/buffer
  payload；这些 target 不会伪装成 MMIO 地址
- Cond、Loop、Delay

表达式域为 Const、Var、BinOp、Ite、Bits、Top。switch/if 的互斥 RMW 路径会合成为嵌套 Ite，保留每条路径对原始读值的独立变换；仍无法解析的值才保留 Top 并阻止 strict readiness。Computed 地址保留完整动态 offset，只有包含不安全调用或未绑定成员的 computed expression 才阻止 readiness。

RIS leaf op 还包含 `op_id`、source evidence、reliability、address/value/path precision 和 access domain。已识别 MMIO、regmap、I2C/SMBus、公共 MFD transaction API、直接 volatile 解引用与 inline asm 都进入 access accounting；无法 lowering 的访问不会静默消失。显式 source-level CFG 记录 block、pred/succ、dominance/post-dominance、join、goto edge、backedge 与 loop header。结构化路径由 Z3 检查可满足性与 switch 互斥性；规范、静态有界的 `for` 循环可被证明并生成。简单参数型 early exit 和可界定的前向 goto 会转成 continuation guard，后向 goto 与未证明循环仍由 control accounting 显式阻塞。

跨函数内联采用有界传播。若被 dedup 的 helper 自有 source site 没有出现在任何保留模块中，C15 会仅保留该 helper 中尚未覆盖的 definition-owned register evidence frontier，使访问不会消失。当前尚无正式 `Call`/call-context verifier，因此只要存在 helper flattening，无论是否触发 rescue，strict 与 LLM synthesis readiness 都保持 false；site coverage 不会被冒充为调用路径证明。

生成 C 中的每个 Read/Write/RMW 还必须携带 `op_id + canonical digest` lowering receipt。独立 oracle 对 generation contract 做 exactly-once 检查，拒绝 missing、duplicate、unknown、rejected、kind mismatch 和 digest drift。C16 令 contract/digest 构建保持纯函数，并把该 verifier 强制接入 LLM 初次生成与 compile/QEMU/trace 每轮修复；候选只有通过 frozen contract 后才会原子替换当前 C。该 gate 证明操作归属完整性；表达式和控制路径的独立 AST 等价验证仍是下一阶段工作。

C17 为公共 harness/bare-metal lowering 增加 `__rh_op_<op_id>` LabelStmt + direct CompoundStmt。libclang oracle 现可拒绝悬空 receipt、错误 primitive kind/width/endianness/W1C、RMW ownership 和未锚定额外 MMIO。contract 同时区分 `write_from_read` 与 `intrinsic_rmw`，修复了旧生成器对 dataflow RMW 重复读取硬件的错误。地址、值变换、guard/order、Linux 专用 emitter 与 Formal `Call` 仍是明确 blocker。

C18 将 backend lowering recipe 绑定到 canonical Formal，禁止 probe success-path 重写后重新猜测 primitive ownership；同时用独立 lowering plan 将 DWC2 H/B 的 3608 个 contract ops 精确分解为 3182 lowered + 426 `blocked_unsupported_loop`，不为未证明循环伪造 receipt/anchor。direct-read-return 也改为只信任 MMIO classifier 证明的 return provenance，不再因 `device_property_read_bool` 一类名称含 `read` 的普通 helper 篡改 RMW 数据流。

C19 将 lowering plan 扩展到 Linux，并与真实 receipt report 做授权集对账。DWC2 精确分为 2023 个 definition candidate、77 个 evidence-only ops、426 个 loop blocker、898 个 root blocker与 184 个 lifecycle blocker；C67X00/ASPEED 也分别闭合为 26/6 和 133/21 authorized/blocked。新的 versioned DeviceSpec JSON 为 verifier 和 LLM bundle 提供严格、可重载的函数/root 证据。定义已发射与 runtime 已注册仍明确分离。

C20 对 Linux 生成代码增加独立 required-subset leaf AST 与 registration AST oracle，并由 `backend-lowering-plan-v3` 依据实际 generated-C artifact SHA、精确 Kbuild `.o.cmd` context、操作集合、callback/function USR、typed field、精确对象路径、registration call 和 module-init root 重建有效身份链。FTGPIO 的 35 个 strict candidate 全部通过；DWC2 的 2023 个 candidate 虽全部通过 leaf AST，只有 62 个落入 v1 支持的 registration route，因此 Linux strict 仍为 false。DWC2 的 H/B 仍是 3182 lowered + 426 loop-blocked，Linux 仍是 2100 authorized + 1508 blocked。该证明尚不覆盖 kernel callback invocation、callback 内路径语义或 USB endpoint/gadget/HCD lifecycle；机器冻结摘要见 [`research/experiments/results/c20-linux-registration-attestation.json`](research/experiments/results/c20-linux-registration-attestation.json)。

Linux lowering 会区分 callback table 的具体实例。GPIO 动态 `gpio_irq_chip.init_hw` 绑定会按字段语义归类；clock provider 会保留多套 `clk_ops`、纯标量 rate 算术、源码内 helper、父时钟/provider 注册以及对应 OF 变体。Sodaville 的 PCI ID、12-line GPIO generic dat/set/dirout 行为和 mask/unmask/EOI IRQ lifecycle 由版本化源码保守恢复。只有经过显式 source-private 重绑定且真实 Kbuild 通过的 callback 才可消除 unsupported marker。

完整 pipeline 可生成：

- .ris：寄存器交互序列
- .dspec：FunctionSpec/DeviceSpec
- .bind：后端绑定
- .facts：源码结构、callback、resource 等事实
- .formal.json：包含完整 provenance 的 canonical Formal RIS
- generation-contract.json：面向确定性后端和 LLM 的逐操作生成契约、claim scope 与 readiness
- harness、bare-metal 和 Linux C

实验聚合信息使用 JSON 保存，以便论文表格和复现脚本机器读取；RIS 本身仍使用正式的 .ris 文本语言。

## 快速开始

~~~bash
git submodule update --init
./tools/build/prepare_kernel.sh build

./run.sh test
./run.sh extract benchmarks/drivers/baseline/gpio-ftgpio010.c artifacts/output/ftgpio.ris
./run.sh spec benchmarks/drivers/baseline/gpio-ftgpio010.c artifacts/output/ftgpio.dspec
./run.sh gen benchmarks/drivers/baseline/edu.c linux artifacts/output/edu_drv.c
./run.sh driver benchmarks/drivers/baseline/edu.c artifacts/output/edu
./run.sh reliability benchmarks/drivers/baseline/gpio-ftgpio010.c
~~~

直接调用 python3 -m extractor 时，分析类子命令支持 --alias-mode off|auto|required。

## 复现实验和论文

~~~bash
./run.sh test
python3 qa/verification/check_generalization_guard.py
python3 qa/verification/run_zero_shot_holdout.py
python3 qa/verification/materialize_holdout_contexts.py
python3 qa/verification/run_zero_shot_matrix.py
python3 qa/verification/run_matrix.py
python3 qa/verification/run_multisource_matrix.py
python3 qa/verification/run_clock_model_boundary.py
python3 qa/verification/c67x00_hpi_trace_oracle.py \
  --output research/experiments/results/c67x00-hpi-oracle.json
python3 qa/verification/dwapb_banked_oracle.py \
  --output research/experiments/results/dwapb-banked-oracle.json
./run.sh qemu-experiments
python3 qa/verification/reliability_report.py \
  --output research/experiments/results/reliability.json
python3 qa/verification/ris_mutation_oracle.py
python3 qa/verification/ris_trace_oracle.py
python3 qa/verification/ftgpio_trace_oracle.py
python3 tools/reporting/generate_paper_results.py
(cd research/paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~

权威结果：

- research/experiments/results/matrix.json
- research/experiments/results/reliability.json
- research/experiments/results/multisource-matrix.json
- research/experiments/results/clock-model-boundary.json
- research/experiments/results/c67x00-hpi-oracle.json
- research/experiments/results/dwapb-banked-oracle.json
- research/experiments/results/sdhci-accessor-oracle.json
- research/experiments/results/virtio-state-oracle.json
- research/experiments/results/zero-shot-v1.json
- research/experiments/results/zero-shot-contexts.json
- research/experiments/results/zero-shot-matrix.json
- research/experiments/results/qemu.json
- research/paper/generated_results.tex（自动生成，不手改）
- research/paper/paper.pdf

详细环境和判定标准见 [REPRO.md](REPRO.md)。

实测复盘：

- [LLM 直接合成驱动时的问题与能力边界](docs/plans/llm-limitations.md)
- [Codex 作为工程代理完成 v4→v5 时的问题与能力边界](docs/retrospectives/engineering-agent-retrospective-v5.md)
- [Codex 作为工程代理完成 v5→v6 时的问题与能力边界](docs/retrospectives/engineering-agent-retrospective-v6.md)
- [Codex 作为工程代理完成 v6→v7 时的问题与能力边界](docs/retrospectives/engineering-agent-retrospective-v7.md)
- [Codex 作为工程代理完成 v7→v8 时的问题与能力边界](docs/retrospectives/engineering-agent-retrospective-v8.md)
- [Codex 作为工程代理完成 sequential GPIO/SDHCI/W1C 阶段的问题与能力边界](docs/retrospectives/engineering-agent-retrospective-v9.md)
- [Codex 作为工程代理完成 zero-shot 12/12 与 DW APB multi-bank 时的问题与能力边界](docs/retrospectives/engineering-agent-retrospective-v10.md)
- [C11 subsystem library summaries 与零样本边界](docs/milestones/subsystem-library-summaries-c11.md)
- [C15 coverage-aware callee rescue 与 call-context fail-closed 边界](docs/milestones/callee-rescue-c15.md)
- [C16 generation contract 纯函数与 LLM 原子 attestation gate](docs/milestones/generation-attestation-c16.md)
- [C17 generated-C AST anchors、primitive ownership 与负向结果](docs/milestones/generated-c-ast-anchors-c17.md)
- [C18 DWC2 lowering plan、canonical recipe 与 read provenance](docs/plans/dwc2-lowering-plan-c18.md)
- [C19 Linux definition plan、DeviceSpec JSON 与 runtime boundary](docs/plans/linux-definition-plan-c19.md)
- [C20 Linux generated-AST、registration identity attestation 与 fail-closed 边界](docs/milestones/linux-registration-attestation-c20.md)

## 依赖

- Python 3
- Python clang.cindex 与 libclang 18
- C 编译器和 GNU make
- Linux 内核构建依赖
- QEMU x86_64（仅运行时实验）
- cpio、静态链接 libc/工具链（用于 guest rootfs）

LLM 不是确定性测试、矩阵或 QEMU 结果的依赖。可选 synthesis loop 通过 REHARNESS_LLM_CMD 接入外部模型。

## 根目录契约

~~~text
run.sh
artifacts/  benchmarks/  docs/      examples/
platform/   qa/          research/  scripts/
src/        tools/       vendor/
~~~
