# 复现 reharness 论文结果

本流程复现 19-driver 提取/三后端编译矩阵、两个确定性 QEMU 实验，以及由机器结果生成的论文表格。主结果不调用 LLM。

`paper-artifact-v8` 保留此前论文基线。当前 C11 结果 JSON 中的 `reharness_commit` 固定为 `15a87954461ed7652f3271ead47f2b1119797ba8`，表示 subsystem summaries 与精确 callback trace oracle 的实现提交；随后纳入结果、日志和论文 PDF 的提交只封存制品，不改变该实现 SHA。

## 环境

需要：

- Python 3、clang.cindex、libclang 18
- GNU make、C 编译器和 Linux 内核构建依赖
- QEMU qemu-system-x86_64，包含 -device edu
- cpio 及构造 initramfs 所需的宿主工具
- latexmk/pdfLaTeX（仅论文构建）

项目不依赖宿主机上的外部 driver 或 Linux 源码目录。drivers/ 已纳入仓库，linux/ 由 submodule 固定版本。

## 1. 初始化与构建实验内核

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build
~~~

脚本使用 kernel/linux-x86_64.config，在 kernel/build/ out-of-tree 构建，不修改 submodule 工作树。固定内核 release 和 commit 会写入实验 JSON。

## 2. 回归测试

~~~bash
./run.sh test
~~~

预期：101 passed, 0 failed。测试前会打印 `zero-shot-v1` guard 报告并要求 `passed=true`。

## 2a. 零样本 holdout 与 Kbuild compile context

~~~bash
python3 verification/check_generalization_guard.py
python3 verification/run_zero_shot_holdout.py
~~~

`drivers/holdout/zero-shot-v1.json` 在首次运行新驱动前冻结 12 个 source、Linux commit 与 SHA-256。guard 扫描 extractor/ 和 generator/，禁止加入 holdout driver name、basename 或私有前缀特例。

首个固定案例是 `linux/drivers/gpio/gpio-altera.c`。验证器分别以 `--compile-context off` 和 `required` 运行完整 pipeline。required 模式从 `kernel/build/drivers/gpio/.gpio-altera.o.cmd` 导入真实 Kbuild preprocessing context；也可以通过 `--compile-commands PATH` 或 `REHARNESS_COMPILE_COMMANDS` 提供 compile database。

验收要求：guard 通过、context provenance 可用、目标源码无 clang error、source access accounting strict、三后端编译、函数 inventory 稳定、RIS/DeviceSpec 无语义回退。权威输出：`experiments/results/zero-shot-v1.json`。

该结果不要求新驱动 strict-ready。当前 gpio-altera 的 18 个 source access 全部 accounting，三个后端均编译，但仍有 polling loop 和 Linux source-private/lifecycle blocker；这是保留的泛化边界。

## 2b. 12-driver exact-context 与 zero-shot matrix

~~~bash
python3 verification/materialize_holdout_contexts.py
python3 verification/run_zero_shot_matrix.py
~~~

materializer 按 `drivers/holdout/zero-shot-v1-contexts.json` 构建 7 个 profile：ARM v4t/v5/v7、Moxart、Dove、PowerPC Wii，以及固定的 x86 实验 build。PowerPC profile 需要 `ld.lld`；脚本依次检查 `REHARNESS_LD_LLD`、`PATH` 和 Rust toolchain 的 `gcc-ld/ld.lld`。9 个案例使用对应架构 defconfig，3 个使用 pinned x86 context。`gpio-ge` 的 x86 context 明确是 non-native：clang-18 不接受原生 85xx 的 `-mcpu=8540`，该限制保留在 recipe 和结果中。

每个 object 的 `.cmd`、`.config`、raw command 和合并 compile database 均记录 SHA-256。矩阵对所有案例强制传入：

~~~text
--compile-commands output/zero-shot-contexts/compile_commands.json
--compile-context required
~~~

当前结果：

~~~text
exact compile context=12/12
pipeline completed=12/12
harness/bare-metal/Linux compile=12/12
no_register_access=0/12
strict-ready: harness=5/12 bare-metal=5/12 Linux=5/12
first common semantic blocker=conservative_loop (3/12)
~~~

三个 clock 案例以及 `gpio-ts4800`、`gpio-ge` 现在三个后端共同 strict-ready。后两个案例的 harness 与 bare-metal 分别执行 7/7 合成 callbacks，并由独立解释器核对每次访问的类型、offset 和值；GE 额外验证 big-endian byte order，TS4800 验证 16-bit accessor。DW APB 的 callback oracle 也通过，但 computed address 与 loop blocker 仍保留；CLPS711x variant、未建模 SDHCI core callback、virtio domain 和 clang diagnostics 同样不会被 runner 掩盖。

权威输出：`experiments/results/zero-shot-contexts.json` 和 `experiments/results/zero-shot-matrix.json`。详细设计与问题记录见 `docs/zero-shot-matrix-c10.md`。

## 3. 19-driver 确定性矩阵

~~~bash
python3 verification/run_matrix.py
~~~

输出：experiments/results/matrix.json。

当前冻结聚合值：

~~~text
drivers=19 ops=469 symbolic=356 fixed=74 computed=25
rmw=88 conditions=117 registers=157 unknown_value=0
harness_compile=19 baremetal_compile=19 linux_compile=19
strict_ready: harness=6 baremetal=6 linux=7
llm_synthesis_ready=13
~~~

*_compile 只表示生成物通过相应编译器/Kbuild。*_ready 还要求没有 Top、unsafe computed address、目标源文件 clang error 或 REHARNESS_UNSUPPORTED 状态绑定；可精确 lowering 的 computed address（例如 PL061 banked GPIO）不再被误判为 blocker。Highbank 只有 Linux 专用 clock lowering ready；其轮询循环仍阻止通用 harness/bare-metal readiness。

实验内核配置固定启用 `CONFIG_COMMON_CLK=y`，用于验证生成的 clock framework 注册路径；该配置随 artifact 版本化。

## 3a. 机器可读可靠性报告

~~~bash
python3 verification/reliability_report.py \
  --output experiments/results/reliability.json
~~~

报告逐驱动记录 source access accounting、显式 CFG/control accounting、SMT path validation、op ID/evidence 覆盖和 alias/toolchain 范围。当前单源默认 `alias-mode=off` 的 scoped strict 为 8/19，因此这些结果仍为 `whole_program_complete=false`。该字段现在由严格 gate 合取计算；linked manifest fixture 可达到 true，但其 scope 明确为 `manifest-internal`，不包含外部 kernel/subsystem 语义。

## 3b. Clock 算术 oracle 与泛化边界

~~~bash
python3 verification/run_clock_model_boundary.py
~~~

输出：`experiments/results/clock-model-boundary.json`。

Highbank 的生成 callback 会在独立 userspace MMIO shim 中执行并与 Python reference 比较：22 个基线用例全部通过，PLL divq、A9 bus shift 和 periclk increment 三类 mutation 均至少被一个用例检出。该 oracle 验证当前版本化公式，但不是 Highbank 真实硬件等价证明。

同一分析器必须保守拒绝 Visconti PLL；JSON 会记录 `pll_base`、`rate_table/rate_count`、`lock` 和未绑定 private value 等原因。这个负例用于防止把 Highbank 的受限语法 lowering 错写成通用 clock source-private 支持。

## 3c. 真实多源 Linux 驱动矩阵

~~~bash
python3 verification/run_multisource_matrix.py
~~~

该实验只接受至少 4 个 C 文件的 manifest，并检查所有文件确实出现在固定 Linux 源码的同一 Kbuild `*-y` 对象列表中。验证器还会在临时副本中调用原始 Kbuild，不修改 Linux submodule；记录严格 modpost 结果及 USB core 外部符号缺失时的 warning-only 重试。当前规模阶梯：

~~~text
c67x00:      4 TUs,  2239 lines,  89 functions,   38 ops
aspeed-vhub: 5 TUs,  3540 lines,  92 functions,  154 ops
dwc2:       10 TUs, 21668 lines, 445 functions, 4202 ops
aggregate:  19 TUs, 27447 lines, 626 functions, 4394 ops, 948 RMW
calls:      974 internal, 223 cross-TU, 223 resolved, 578 MMIO-propagating
MMIO:       907 source primitives, 1084 direct AST ops, 3742 emitted RIS ops
compile:    harness=3/3 bare-metal=3/3 Linux=2/3 original-Kbuild=3/3
~~~

固定实验内核未启用 usbcore，因此三个原始模块的严格 modpost 都会报告未解析的 USB 导出符号。验证器只在确认失败属于该类外部符号后，以 `KBUILD_MODPOST_WARN=1` 完成 `.ko` 链接，并在 JSON 中保留 `strict_success=false`、符号列表和完整日志。

权威输出：`experiments/results/multisource-matrix.json`。DWC2 与 C67X00 的生成 Linux 聚合模块通过；Aspeed-vHub 因 endpoint 生命周期和未建模 subsystem state 保守失败。脚本因此仍预期非零退出，不能把 2/3 改写成 3/3。

## 3d. C67X00 linked SVF 与 HPI oracle

~~~bash
python3 -m extractor driver \
  -s drivers/multisource/c67x00.json \
  -o output/c67x00-linked-svf \
  --alias-mode required
python3 verification/c67x00_hpi_trace_oracle.py \
  --output experiments/results/c67x00-hpi-oracle.json
~~~

required run 会将 4 个 TU 的 bitcode 链接后执行一次 WPA。当前 linked bitcode SHA-256 为 `f0748140aa0b2e2ee43f95596ba461732148052b7b8841453696f142028388c2`，`linked_alias_complete=true`。C67X00 没有新增普通 pointer alias；其主要难点是 HPI aggregate state，而不是 alias 缺失。

HPI oracle 检查 5 个原始 primitive case 和 4 个原始 C↔RIS differential case，并要求 register index、regstep、wrapper target、operation order 四类 mutation 全被检出。C67X00 当前仍非 strict-ready：一个 switch exclusivity 和一个 loop proof gate 未完成，且完整 HCD lifecycle 仍是显式 unsupported；编译成功不等于完整语义证明。

## 4. 确定性 QEMU 实验

~~~bash
verification/run_qemu_experiments.sh
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
op coverage 16/16
register coverage 7/7
QEMU_EXPERIMENTS_OK
~~~

权威输出：

- experiments/results/qemu.json
- experiments/results/qemu-edu-serial.log
- experiments/results/qemu-ftgpio010-serial.log
- experiments/results/qemu-ftgpio010-trace.txt

## 5. 生成论文数据并构建 PDF

~~~bash
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~

tools/generate_paper_results.py 从 matrix.json 与 qemu.json 生成 paper/generated_results.tex。不要手工编辑该文件。

## 可选：SVF 与 LLM

SVF 默认关闭以保证快速、稳定复现：

~~~bash
python3 -m extractor extract -s drivers/test/gpio-ftgpio010.c \
  --alias-mode auto -o output/ftgpio-svf.ris
~~~

工具位置和超时通过 REHARNESS_SVF_* 环境变量配置；required 模式在工具缺失、bitcode/link/WPA 失败时返回错误，不允许静默退回逐 TU 或空 alias。多源结果记录 linked bitcode SHA、TU 数、工具版本与 source provenance。

LLM synthesis 是独立的可选路径，通过 REHARNESS_LLM_CMD 接入外部命令。模型和 endpoint 具有非确定性，因此 LLM 结果不计入论文的 19/19 编译和 QEMU headline claims。

## 从干净 checkout 完整执行

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build
./run.sh test
python3 verification/check_generalization_guard.py
python3 verification/run_zero_shot_holdout.py
python3 verification/run_matrix.py
python3 verification/run_multisource_matrix.py
python3 verification/run_clock_model_boundary.py
python3 verification/c67x00_hpi_trace_oracle.py --output experiments/results/c67x00-hpi-oracle.json
verification/run_qemu_experiments.sh
python3 verification/reliability_report.py --output experiments/results/reliability.json
python3 verification/ris_mutation_oracle.py
python3 verification/ris_trace_oracle.py
python3 verification/ftgpio_trace_oracle.py
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~
