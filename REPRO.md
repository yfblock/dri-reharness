# 复现 reharness 论文结果

本流程复现 19-driver 提取/三后端编译矩阵、两个确定性 QEMU 实验，以及由机器结果生成的论文表格。主结果不调用 LLM。

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

预期：47 passed, 0 failed。

## 3. 19-driver 确定性矩阵

~~~bash
python3 verification/run_matrix.py
~~~

输出：experiments/results/matrix.json。

当前冻结聚合值：

~~~text
drivers=19 ops=425 symbolic=314 fixed=64 computed=33
rmw=71 conditions=58 registers=141 unknown_value=0
harness_compile=19 baremetal_compile=19 linux_compile=19
strict_ready: harness=7 baremetal=7 linux=5
llm_synthesis_ready=12
~~~

*_compile 只表示生成物通过相应编译器/Kbuild。*_ready 还要求没有 Top、unsafe computed address、目标源文件 clang error 或 REHARNESS_UNSUPPORTED 状态绑定；可精确 lowering 的 computed address（例如 PL061 banked GPIO）不再被误判为 blocker。

实验内核配置固定启用 `CONFIG_COMMON_CLK=y`，用于验证生成的 clock framework 注册路径；该配置随 artifact 版本化。

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
6. 启动 QEMU 并按 RIS 比对 probe 的 MMIO offset/order。

成功标志：

~~~text
EDU_TRACE_OK
TRACE_MATCH_OK
module coverage 1/1
op coverage 4/4
register coverage 4/4
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

工具位置和超时通过 REHARNESS_SVF_* 环境变量配置；required 模式在工具缺失或失败时返回错误。

LLM synthesis 是独立的可选路径，通过 REHARNESS_LLM_CMD 接入外部命令。模型和 endpoint 具有非确定性，因此 LLM 结果不计入论文的 19/19 编译和 QEMU headline claims。

## 从干净 checkout 完整执行

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build
./run.sh test
python3 verification/run_matrix.py
verification/run_qemu_experiments.sh
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
~~~
