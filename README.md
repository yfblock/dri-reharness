# reharness

reharness 从 Linux C 设备驱动中提取形式化寄存器交互序列（RIS），推断后端无关的设备语义，并确定性生成 userspace harness、bare-metal C 和 Linux 内核模块。

核心分析使用 libclang AST、过程间有限深度内联、流敏感数据流与污点追踪。相比正则基线，它能恢复宏寄存器偏移、包装函数中的 MMIO、分支条件、地址算术和 read-modify-write（RMW）变换。

## 当前状态

- 版本化语料：drivers/test/ 内含 19 个单源测试驱动；drivers/multisource/ 包含真实 Kbuild 多源模块 manifest。
- 版本化内核：linux/ 是固定到实验 commit 的 Git submodule。
- 三个确定性后端：19/19 均可编译。
- 严格语义 readiness：harness 7/19、bare-metal 7/19、Linux 5/19；可编译不等于语义完整。
- 多源规模：C67X00（4 C/2239 LoC）与 ASPEED vHub（5 C/3540 LoC），三后端均可编译。
- 测试套件：51 tests。
- QEMU：edu 通过值级 oracle；gpio-ftgpio010 通过 probe MMIO offset/order oracle。
- SVF 别名分析：off、auto、required，默认 off，可通过 REHARNESS_SVF_* 配置工具路径和超时。

当前冻结实验结果来自 experiments/results/matrix.json：

| 驱动数 | Ops | Symbolic | Fixed | Computed | RMW | Conditions | Registers |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 19 | 425 | 314 | 64 | 33 | 71 | 58 | 141 |

地址分类是刻意分开的：只有可静态命名的访问记为 Symbolic；常量偏移和运行时索引分别保留为 Fixed 与 Computed，不会伪造成“100% symbolic”。

## RIS 与语义输出

RIS 操作包括：

- Read：var := R(width, addr)
- Write：W(width, addr) = expr
- ReadModifyWrite：RMW(width, addr) = transform
- Cond、Loop、Delay

表达式域为 Const、Var、BinOp、Ite、Bits、Top。switch/if 的互斥 RMW 路径会合成为嵌套 Ite，保留每条路径对原始读值的独立变换；仍无法解析的值才保留 Top 并阻止 strict readiness。Computed 地址保留完整动态 offset，只有包含不安全调用或未绑定成员的 computed expression 才阻止 readiness。

完整 pipeline 可生成：

- .ris：寄存器交互序列
- .dspec：FunctionSpec/DeviceSpec
- .bind：后端绑定
- .facts：源码结构、callback、resource 等事实
- harness、bare-metal 和 Linux C

实验聚合信息使用 JSON 保存，以便论文表格和复现脚本机器读取；RIS 本身仍使用正式的 .ris 文本语言。

## 快速开始

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build

./run.sh test
./run.sh extract drivers/test/gpio-ftgpio010.c output/ftgpio.ris
./run.sh spec drivers/test/gpio-ftgpio010.c output/ftgpio.dspec
./run.sh gen drivers/test/edu.c linux output/edu_drv.c
./run.sh driver drivers/test/edu.c output/edu
~~~

直接调用 python3 -m extractor 时，分析类子命令支持 --alias-mode off|auto|required。

## 复现实验和论文

~~~bash
./run.sh test
python3 verification/run_matrix.py
python3 verification/run_multisource_matrix.py
verification/run_qemu_experiments.sh
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~

权威结果：

- experiments/results/matrix.json
- experiments/results/multisource-matrix.json
- experiments/results/qemu.json
- paper/generated_results.tex（自动生成，不手改）
- paper/paper.pdf

详细环境和判定标准见 [REPRO.md](REPRO.md)。

## 依赖

- Python 3
- Python clang.cindex 与 libclang 18
- C 编译器和 GNU make
- Linux 内核构建依赖
- QEMU x86_64（仅运行时实验）
- cpio、静态链接 libc/工具链（用于 guest rootfs）

LLM 不是确定性测试、矩阵或 QEMU 结果的依赖。可选 synthesis loop 通过 REHARNESS_LLM_CMD 接入外部模型。

## 目录

~~~text
drivers/                 版本化的 19-driver evaluation corpus
drivers/multisource/     真实 Linux 多源 Kbuild 模块 manifest（4+ C 文件）
linux/                   固定 commit 的 Linux Git submodule
kernel/                  实验 config、patch、构建说明和 out-of-tree build
extractor/               AST 提取、数据流、语义推断、metrics、CLI
generator/               harness / bare-metal / Linux 后端
verification/            compile matrix、QEMU experiments、trace comparison
experiments/results/     机器可读的冻结结果与日志
tools/                   kernel、instrumentation、paper result 工具
paper/                   论文源文件、自动结果宏和 PDF
tests/                   回归测试
~~~
