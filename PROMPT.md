# Reharness 当前维护提示

reharness 是一个面向 Linux C 驱动的 AST/RIS 提取、语义推断和多后端生成系统。继续维护时，以代码、测试和 experiments/results/*.json 为准，不要恢复历史文档中的手抄统计。

## 已完成基线

- drivers/：19 个版本化测试驱动，不是外部 symlink。
- linux/：固定 commit 的 Git submodule。
- extractor：libclang、流敏感数据流、过程间内联、RMW 变换、callback enclosing-struct 推断。
- alias：off、auto、required，默认 off，SVF 为可选增强。
- specs：.ris、.dspec、.bind、.facts。
- generators：harness、bare-metal、Linux；19/19 均编译。
- Linux：确定性 platform、PCI、GPIO/IRQ 和 QEMU edu lifecycle；unsupported state 显式标记。
- tests：42 passed。
- QEMU：edu 值级 oracle 和 gpio-ftgpio010 offset/order oracle 均通过。
- paper：统计由 tools/generate_paper_results.py 从实验 JSON 自动生成。

冻结矩阵：

~~~text
19 drivers, 393 ops
260 symbolic, 63 fixed, 56 computed
67 RMW, 60 conditions, 124 registers
compile: harness=19, bare-metal=19, Linux=19
strict ready: harness=1, bare-metal=1, Linux=1
LLM synthesis ready=10
~~~

## 重要语义约束

- 不得把 fixed/computed address 计为 symbolic。
- 不得把“编译通过”写成“语义 ready”。
- switch 多路径不能安全合并时保留 Top。
- source-private state 只能中性化并输出 REHARNESS_UNSUPPORTED，不能伪造语义。
- 确定性论文实验不得调用 LLM。
- paper/generated_results.tex 是生成文件，不能手改。

## 标准验证顺序

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build
./run.sh test
python3 verification/run_matrix.py
verification/run_qemu_experiments.sh
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
git diff --check
~~~

## 已知限制

- 路径不敏感，部分 switch RMW 为 Top。
- computed/indexed MMIO 不能总是静态命名。
- AHCI 等驱动仍存在内核配置相关 clang diagnostics 和 source-private subsystem state。
- Linux 虽为 19/19 Kbuild，严格 ready 仅 1/19。
- SVF 外部工具链成本较高，默认关闭。
- LLM synthesis 非确定性，只作为可选补全路径。

继续工作时应优先增加可验证语义覆盖，而不是通过宽松 readiness 或中性 stub 美化数字。
