# 复现 reharness 论文结果

本流程复现 19-driver 提取/三后端编译矩阵、两个确定性 QEMU 实验，以及由机器结果生成的论文表格。主结果不调用 LLM。

结果 JSON 中的 `reharness_commit` 记录执行实验时的代码提交；在最终 artifact tag 前重跑得到的工作树结果会暂时指向上一提交，封存提交和 tag 用于固定代码、结果、日志与论文 PDF 的完整组合。

## 环境

需要：

- Python 3、clang.cindex、libclang 18
- GNU make、C 编译器和 Linux 内核构建依赖
- QEMU qemu-system-x86_64，包含 -device edu
- cpio 及构造 initramfs 所需的宿主工具
- latexmk/pdfLaTeX（仅论文构建）

项目不依赖宿主机上的外部 driver 或 Linux 源码目录。驱动输入位于
`benchmarks/drivers/`，`vendor/linux/` 由 submodule 固定版本。

## 1. 初始化与构建实验内核

~~~bash
git submodule update --init
./tools/build/prepare_kernel.sh build
~~~

脚本使用 `platform/kernel/linux-x86_64.config`，在
`platform/kernel/build/` out-of-tree 构建，不修改 submodule 工作树。固定内核
release 和 commit 会写入实验 JSON。

## 2. 回归测试

~~~bash
./run.sh test
~~~

预期：205 passed, 0 failed（15 repository-path + 143 core + 8 generated-C
AST + 10 Linux registration AST + 21 lowering-plan + 1 C20 readiness + 2
read-provenance + 5 DeviceSpec JSON）。测试前会打印 `zero-shot-v1` guard
报告并要求 `passed=true`。

## 2a. 零样本 holdout 与 Kbuild compile context

~~~bash
python3 qa/verification/check_generalization_guard.py
python3 qa/verification/run_zero_shot_holdout.py
~~~

`benchmarks/drivers/holdout/zero-shot-v1.json` 在首次运行新驱动前冻结 12 个 source、Linux commit 与 SHA-256。guard 扫描 src/extractor/ 和 src/generator/，禁止加入 holdout driver name、basename 或私有前缀特例。

首个固定案例是 `vendor/linux/drivers/gpio/gpio-altera.c`。验证器分别以 `--compile-context off` 和 `required` 运行完整 pipeline。required 模式从 `platform/kernel/build/drivers/gpio/.gpio-altera.o.cmd` 导入真实 Kbuild preprocessing context；也可以通过 `--compile-commands PATH` 或 `REHARNESS_COMPILE_COMMANDS` 提供 compile database。

验收要求：guard 通过、context provenance 可用、目标源码无 clang error、source access accounting strict、三后端编译、函数 inventory 稳定、RIS/DeviceSpec 无语义回退。权威输出：`research/experiments/results/zero-shot-v1.json`。

该冻结首例只验证 holdout、context provenance 和无特例策略；最终 zero-shot matrix 另外通过 masked-W1C drain contract 和 mutation oracle 验证 gpio-altera，不应把首例脚本本身误解为完整 strict-readiness 证明。

## 2b. 12-driver exact-context 与 zero-shot matrix

~~~bash
python3 qa/verification/materialize_holdout_contexts.py
python3 qa/verification/run_zero_shot_matrix.py
~~~

materializer 按 `benchmarks/drivers/holdout/zero-shot-v1-contexts.json` 构建 7 个 profile：ARM v4t/v5/v7、Moxart、Dove、PowerPC Wii，以及固定的 x86 实验 build。PowerPC profile 需要 `ld.lld`；脚本依次检查 `REHARNESS_LD_LLD`、`PATH` 和 Rust toolchain 的 `gcc-ld/ld.lld`。9 个案例使用对应架构 defconfig，3 个使用 pinned x86 context。`gpio-ge` 的 x86 context 明确是 non-native：clang-18 不接受原生 85xx 的 `-mcpu=8540`，该限制保留在 recipe 和结果中。

每个 object 的 `.cmd`、`.config`、raw command 和合并 compile database 均记录 SHA-256。矩阵对所有案例强制传入：

~~~text
--compile-commands artifacts/output/zero-shot-contexts/compile_commands.json
--compile-context required
~~~

当前结果：

~~~text
exact compile context=12/12
pipeline completed=12/12
harness/bare-metal/Linux compile=12/12
no_register_access=0/12
strict-ready: harness=7/12 bare-metal=7/12 Linux=5/12 all=5/12
cases with register hardware interactions=11/12
first common RIS semantic blocker=call_context (5 drivers)
~~~

GPIO callback runner 与独立 source differential 覆盖 width、endianness、shadow state 和 banked computed address。SDHCI NPCM、Dove、HLWD 通过 accessor/source lifecycle contract；virtio-input 的 config/virtqueue 被建模为 subsystem state，因此不伪造成 MMIO。DW APB 的每-bank chip ownership、selector/shadow、PM context、source-proven IRQ bank、parent IRQ dispatch 以及 ack/mask/type 语义由 13 个 mutation 覆盖。

权威输出：`research/experiments/results/zero-shot-contexts.json` 和 `research/experiments/results/zero-shot-matrix.json`。详细设计与问题记录见 `docs/experiments/zero-shot-matrix-c10.md`。

## 3. 19-driver 确定性矩阵

~~~bash
python3 qa/verification/run_matrix.py
~~~

输出：research/experiments/results/matrix.json。

当前冻结聚合值：

~~~text
drivers=19 ops=485 symbolic=366 fixed=64 computed=41
rmw=73 conditions=123 registers=157 unknown_value=0 clang_diagnostics=0
harness_compile=18 baremetal_compile=18 linux_compile=17
strict_ready: harness=4 baremetal=4 linux=0 all=0
llm_synthesis_ready=5
~~~

*_compile 只表示生成物通过相应编译器/Kbuild。*_ready 还要求没有 Top、unsafe computed address、目标源文件 clang error 或 REHARNESS_UNSUPPORTED 状态绑定。C19 要求 Linux 定义发射与 runtime registration/callsite 证据分离；C20 进一步要求 required-subset AST、registration AST、实际 generated-C SHA、精确 `.o.cmd` context 和 lowering-plan-v3 逐操作交集全部闭合。

实验内核配置固定启用 `CONFIG_COMMON_CLK=y`，用于验证生成的 clock framework 注册路径；该配置随 artifact 版本化。

## 3a. 机器可读可靠性报告

~~~bash
python3 qa/verification/reliability_report.py \
  --output research/experiments/results/reliability.json
~~~

报告逐驱动记录 source access accounting、显式 CFG/control accounting、SMT path validation、op ID/evidence 覆盖和 alias/toolchain 范围。当前单源默认 `alias-mode=off` 的 scoped strict 为 9/19，因此这些结果仍为 `whole_program_complete=false`。该字段现在由严格 gate 合取计算；linked manifest fixture 可达到 true，但其 scope 明确为 `manifest-internal`，不包含外部 kernel 与 subsystem 语义。

## 3b. Clock 算术 oracle 与泛化边界

~~~bash
python3 qa/verification/run_clock_model_boundary.py
~~~

输出：`research/experiments/results/clock-model-boundary.json`。

Highbank 的生成 callback 会在独立 userspace MMIO shim 中执行并与 Python reference 比较：22 个基线用例全部通过，PLL divq、A9 bus shift 和 periclk increment 三类 mutation 均至少被一个用例检出。该 oracle 验证当前版本化公式，但不是 Highbank 真实硬件等价证明。

同一分析器必须保守拒绝 Visconti PLL；JSON 会记录 `pll_base`、`rate_table/rate_count`、`lock` 和未绑定 private value 等原因。这个负例用于防止把 Highbank 的受限语法 lowering 错写成通用 clock source-private 支持。

## 3c. 真实多源 Linux 驱动矩阵

~~~bash
python3 qa/verification/run_multisource_matrix.py
~~~

该实验只接受至少 4 个 C 文件的 manifest，并检查所有文件确实出现在固定 Linux 源码的同一 Kbuild `*-y` 对象列表中。验证器还会在临时副本中调用原始 Kbuild，不修改 Linux submodule；记录严格 modpost 结果及 USB core 外部符号缺失时的 warning-only 重试。当前规模阶梯：

~~~text
c67x00:      4 TUs,  2239 lines,  89 functions,   38 ops
aspeed-vhub: 5 TUs,  3540 lines,  92 functions,  154 ops
dwc2:       10 TUs, 21668 lines, 445 functions, 4250 ops
aggregate:  19 TUs, 27447 lines, 626 functions, 4446 ops, 959 RMW
calls:      974 internal, 223 cross-TU, 223 resolved, 578 MMIO-propagating
MMIO:       907 source primitives, 1091 direct AST ops, 3794 emitted RIS ops
compile:    harness=3/3 bare-metal=3/3 Linux=3/3 original-Kbuild=3/3
~~~

固定实验内核未启用 usbcore，因此三个原始模块的严格 modpost 都会报告未解析的 USB 导出符号。验证器只在确认失败属于该类外部符号后，以 `KBUILD_MODPOST_WARN=1` 完成 `.ko` 链接，并在 JSON 中保留 `strict_success=false`、符号列表和完整日志。

权威输出：`research/experiments/results/multisource-matrix.json`。三个生成 Linux 聚合模块均通过 Kbuild；Aspeed-vHub 与 DWC2 仍因 endpoint/HCD lifecycle、source-private state、路径和循环证明缺口而非 strict-ready。脚本预期成功退出，但 3/3 编译不能改写成 3/3 语义完成。

## 3d. Linux registration attestation 正反基线

~~~bash
python3 -m extractor driver \
  -s benchmarks/drivers/baseline/gpio-ftgpio010.c \
  -o /tmp/reharness-c20-ftgpio --alias-mode off
python3 -m extractor driver \
  -s benchmarks/drivers/multisource/dwc2.json \
  -o /tmp/reharness-c20-dwc2 --alias-mode off
~~~

FTGPIO 是 v1 支持形态的正向控制：35/35 required AST 与 35/35
registration 均通过，Linux strict 为 true。DWC2 是大型边界控制：2023/2023
required AST 通过，但只有 platform probe 下的 62/2023 operations 注册；1127
个 USB endpoint/gadget/HCD strict operations 全部保持未注册，最终 Linux strict
为 false。两个报告还必须与实际 generated C SHA 和精确 Kbuild `.o.cmd`
context 一致；canonical 可 strict 时，plan v3 会独立重跑两个 AST oracle。

权威冻结摘要：`research/experiments/results/c20-linux-registration-attestation.json`。
详细设计：`docs/milestones/linux-registration-attestation-c20.md`。

## 3e. C67X00 linked SVF 与 HPI oracle

~~~bash
python3 -m extractor driver \
  -s benchmarks/drivers/multisource/c67x00.json \
  -o artifacts/output/c67x00-linked-svf \
  --alias-mode required
python3 qa/verification/c67x00_hpi_trace_oracle.py \
  --output research/experiments/results/c67x00-hpi-oracle.json
~~~

required run 会将 4 个 TU 的 bitcode 链接后执行一次 WPA。当前 linked bitcode SHA-256 为 `f0748140aa0b2e2ee43f95596ba461732148052b7b8841453696f142028388c2`，`linked_alias_complete=true`。C67X00 没有新增普通 pointer alias；其主要难点是 HPI aggregate state，而不是 alias 缺失。

HPI oracle 检查 5 个原始 primitive case 和 4 个原始 C↔RIS differential case，并要求 register index、regstep、wrapper target、operation order 四类 mutation 全被检出。C67X00 当前仍非 strict-ready：一个 switch exclusivity 和一个 loop proof gate 未完成，且完整 HCD lifecycle 仍是显式 unsupported；编译成功不等于完整语义证明。

## 4. 确定性 QEMU 实验

~~~bash
./run.sh qemu-experiments
~~~

脚本会自行：

1. 生成并 Kbuild edu Linux 模块；
2. 构建 guest exerciser，启动 QEMU -device edu；
3. 检查 ID、live-check 和 factorial 的值级 oracle；
4. 生成并 instrument gpio-ftgpio010 模块；
5. 构建 platform device registrar；
6. 启动 QEMU，运行 GPIO chardev exerciser，触发 `get_direction`、方向切换、`get_multiple` 与 `set_multiple`；
7. 由 instrumentation 记录精确 `[rhfn]` 函数边界，并按结构化 Formal RIS JSON 逐调用比对 MMIO offset/order。每个 trace segment 只能匹配一个预期调用，不允许跨 callback 重复计数。

成功标志：

~~~text
EDU_TRACE_OK
TRACE_MATCH_OK
module coverage 6/6
call coverage 7/7
op coverage 13/13
register coverage 8/8
QEMU_EXPERIMENTS_OK
~~~

权威输出：

- research/experiments/results/qemu.json

## 4a. 总线中立 profile 矩阵与自动入口

自动入口根据源码中的 Linux framework registration evidence 选择
`platform-generic`、`pci-generic`、`i2c-generic`、`spi-generic`、
`usb-generic`、`virtio-generic` 或 `mdio-generic`，并把 source
digest、runtime capability、profile-owned fixture 和 subsystem tests 固化进
manifest：

~~~bash
python3 qa/verification/run_auto_driver.py \
  benchmarks/drivers/fixtures/reharness-i2c-sensor.c --dry-run
python3 qa/verification/run_auto_driver.py \
  qa/tests/fixtures/spi-client.json --dry-run
./run.sh profile-matrix
~~~

`profile-matrix` 默认要求 registry 中的全部 runtime-ready 内置 profile（当前为八个）都有完整
QEMU runtime 结果的矩阵。单个
profile 识别成功但缺少 identity、manifest、fixture 或可模拟设备时，自动入口会
返回 `inconclusive`；LangGraph 的 generation 模式仍会执行静态翻译 pipeline，
完成后把结果降级为 `inconclusive`，并保留缺失 runtime 能力。这表示框架能力缺口，
不表示驱动翻译或 runtime 验证通过。

当前八个 runtime-ready profile 的 QEMU runtime 均已在固定实验内核中通过；USB 使用 QEMU
`qemu-xhci`/`usb-serial` 候选 fixture，并额外运行 `dummy_hcd`/`g_zero`/`usbtest`
Linux loopback fixture；Network 使用 synthetic `net_device` fixture，验证注册、
接口发现和 up/down 生命周期。这仍是每类总线/框架一个代表性 fixture，不是对
Linux 子系统所有驱动、竞态、错误注入、网络数据路径和硬件变体的穷尽测试。

`artifacts/profile-matrix/matrix.json` 还包含 `profile_inventory`，列出 registry
中所有已识别类型及其 `runtime_scope`、required/optional capabilities、fixture
kind 和状态。`default-matrix`/`runtime-ready` 表示进入默认 acceptance 集合，
`explicit-only`/`runtime-inconclusive` 表示只能报告能力缺口，plugin profile
则标记为 `plugin-explicit-only`；该目录不会把不可运行的类型升级为通过。

profile catalog 还识别 `amba-generic` 和 `serdev-generic`。它们是源码和 Kbuild
可进入的声明式类型，但由于尚无受信任的 QEMU fixture，`matrix_required=false`，
自动流程对它们保留 `inconclusive`，不会把静态或编译证据升级为 runtime acceptance。
`mdio-generic` 已有 synthetic `mii_bus` fixture，`matrix_required=true`，并由默认
矩阵执行读写、非法地址、probe、绑定和卸载检查。

子系统测试是 manifest-owned 的：`native` 和 `kselftest` 测试作为 guest 用户态
程序构建运行，`tool` 测试用于 Linux 用户态工具/API，`kunit` 测试则要求安全的
kernel module 声明并按 KTAP 日志判定。`provider` 来源由
`benchmarks/subsystem-providers.json` 数据 catalog 注册；它可以 materialize
经过仓库路径校验的 executable/kind，并校验 provider 所属子系统和必需 kernel
module，不能提供任意 shell 命令。每项测试还可声明 `provider` 来源标识和
`required` 阻断策略；当前 SPI profile 运行内核树的 `spidev_test.c`，I2C profile
运行标准 `I2C_RDWR` ABI 测试。catalog 还提供 `linux-clock-kunit`，对应内核
树的 `clk-test.ko`；实验内核配置已生成该模块，但当前没有 manifest 将它列为
required test。因此测试类型不会自动扩大覆盖范围；只有列入某个 profile 的
required capability 并产生成功证据，才会参与 `accepted` 判定。
catalog 同时提供 `linux-usbtest`，对应内核 `usbtest` 模块和
`tools/usb/testusb.c`；USB profile 通过 `dummy_hcd`、`g_zero` 和
`usbtest` 在 guest 内构造 Gadget Zero loopback，并已运行一个 required bulk case。
`i2c-stub` 与外部 `i2c-tools` 尚未作为 profile provider 集成。

QEMU marker 会再经过通用 test-source report：它按 manifest 中的稳定测试名
逐项核对 guest 的 `kind`/provider/required 元数据以及 return code、status 和
success 字段；元数据漂移同样会被记录为 mismatch。缺失、重复、未声明或格式错误的测试证据不会被接受；required 的明确
失败为 `failed`，其余 required 证据缺口为 `inconclusive`。同一报告由
profile runtime 和 `profile-matrix` 共同消费，因此 provider 注册本身不等于
覆盖，且仍不代表整个 Linux 子系统已被验证。

自动 CLI 的 `--dry-run` 只 materialize runtime manifest；正式运行时，缺少
runtime profile 的输入会走 LangGraph generation 做静态翻译和 Kbuild，完成后
仍因 runtime 能力缺失标记为 `inconclusive`。

profile 的通用识别规则由 `benchmarks/driver-profile-definitions.json` 数据目录
加载。目录会 fail-closed 校验 schema、profile id、capability、正则捕获组、
manifest 路径和重复项；自动入口使用传入 `repo_root` 下的目录，因此外部仓库
可以增加新的声明式 profile 而不修改核心 Python runner。具体源文件回归映射
仍位于 `benchmarks/profile-catalog.json`，二者职责不能混用。

子系统 contract 由 `benchmarks/subsystem-contract-definitions.json` 单独注册，
与 transport profile 解耦；一个驱动可以同时拥有 bus profile 和多个 contract。
contract match 会持久化到 profile plan、synthesis evidence 以及 manifest 的
`runtime.subsystem_contracts`。LangGraph analysis 同时输出
`subsystem_contract_verification`；这是只消费 Formal RIS metadata 的
`extractor-metadata` 级别检查，要求声明的 summary group/contract 有完整
callback evidence，并拒绝 `unmodeled_callbacks`。源码 token 识别本身不会
产生静态 `pass`，缺少 summary 保持 `inconclusive`；此报告仍不等于 QEMU、
KUnit 或完整 Linux 子系统验证。generation/experiment workflow 对存在的
contract 还会执行 acceptance gate：只有报告为 `pass` 才能完成，其他状态
不会被 runtime 成功掩盖。

外部 profile plugin 使用同一 manifest/runtime 边界，不需要修改核心 runner：

~~~bash
python3 qa/verification/run_auto_driver.py \
  path/to/driver.c --profile-plugin path/to/profile.py \
  --dry-run --output-dir /tmp/reharness-driver
python3 qa/verification/run_profile_matrix.py \
  --profile-plugin path/to/profile.py \
  --manifest /tmp/reharness-driver/manifest.json \
  --output /tmp/reharness-profile-matrix
~~~

显式 manifest 默认只要求其中发现的 profile；`--required-profile PROFILE` 可重复
传入以固定验收集合。若 profile 的驱动代码通过 `KBUILD_MODNAME` 派生设备节点，
必须在 `ProfilePlan.runtime_overrides.qemu.module` 中声明模块身份，否则 probe
可能成功而用户态设备节点不一致，矩阵会按 required subsystem test 返回 `failed`。
plugin profile 不会自动加入无参数矩阵；缺少 runtime manifest、fixture 或 provider
时保持 `inconclusive`。manifest、fixture、测试 executable 和 provider 仍须经过
路径与 schema 校验，plugin 不能注入任意 shell 命令。

对生成候选使用同一个 manifest/runtime contract，并额外要求候选 trace：

~~~bash
PYTHONPATH=src:qa:qa/verification \
python3 qa/verification/run_profile_matrix.py --require-trace
~~~
- research/experiments/results/qemu-edu-serial.log
- research/experiments/results/qemu-ftgpio010-serial.log
- research/experiments/results/qemu-ftgpio010-trace.txt

## 5. 生成论文数据并构建 PDF

~~~bash
python3 tools/reporting/generate_paper_results.py
(cd research/paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~

`tools/reporting/generate_paper_results.py` 从 matrix.json 与 qemu.json 生成
`research/paper/generated_results.tex`。不要手工编辑该文件。

## 可选：SVF 与 LLM

SVF 默认关闭以保证快速、稳定复现：

~~~bash
python3 -m extractor extract -s benchmarks/drivers/baseline/gpio-ftgpio010.c \
  --alias-mode auto -o artifacts/output/ftgpio-svf.ris
~~~

工具位置和超时通过 REHARNESS_SVF_* 环境变量配置；required 模式在工具缺失、bitcode/link/WPA 失败时返回错误，不允许静默退回逐 TU 或空 alias。多源结果记录 linked bitcode SHA、TU 数、工具版本与 source provenance。

LLM synthesis 是独立的可选路径，默认通过 LangChain 的 OpenAI-compatible
backend 调用模型。使用 `REHARNESS_LLM_BACKEND=pi` 可切回旧 Pi bridge。模型
和 endpoint 具有非确定性，因此 LLM 结果不计入论文的确定性编译矩阵和 QEMU
headline claims。

## 从干净 checkout 完整执行

~~~bash
git submodule update --init
./tools/build/prepare_kernel.sh build
./run.sh test
python3 qa/verification/check_generalization_guard.py
python3 qa/verification/run_zero_shot_holdout.py
python3 qa/verification/materialize_holdout_contexts.py
python3 qa/verification/run_zero_shot_matrix.py
python3 qa/verification/run_matrix.py
python3 qa/verification/run_multisource_matrix.py
python3 qa/verification/sdhci_accessor_oracle.py --output research/experiments/results/sdhci-accessor-oracle.json
python3 qa/verification/virtio_state_oracle.py --output research/experiments/results/virtio-state-oracle.json
python3 qa/verification/dwapb_banked_oracle.py --output research/experiments/results/dwapb-banked-oracle.json
python3 qa/verification/run_clock_model_boundary.py
python3 qa/verification/c67x00_hpi_trace_oracle.py --output research/experiments/results/c67x00-hpi-oracle.json
./run.sh qemu-experiments
python3 qa/verification/reliability_report.py --output research/experiments/results/reliability.json
python3 qa/verification/ris_mutation_oracle.py
python3 src/gate/ris_trace_oracle.py
python3 qa/verification/ftgpio_trace_oracle.py
python3 tools/reporting/generate_paper_results.py
(cd research/paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~
