# Reharness 当前维护提示

reharness 是一个面向 Linux C 驱动的 AST/RIS 提取、语义推断和多后端生成系统。继续维护时，以代码、测试和 experiments/results/*.json 为准，不要恢复历史文档中的手抄统计。

## 已完成基线

- drivers/：19 个版本化测试驱动，不是外部 symlink。
- linux/：固定 commit 的 Git submodule。
- extractor：libclang、流敏感数据流、单/多 Translation Unit 过程间内联、路径条件 RMW/Ite 变换、callback enclosing-struct 推断。
- alias：off、auto、required，默认 off，SVF 为可选增强。
- specs：.ris、.dspec、.bind、.facts。
- generators：harness、bare-metal、Linux；19/19 均编译。
- Linux：确定性 platform、PCI、GPIO/IRQ 和 QEMU edu lifecycle；unsupported state 显式标记。
- multi-source：真实 Kbuild 模块 C67X00（4 C）和 ASPEED vHub（5 C），跨 TU MMIO 传播与三后端编译通过。
- tests：51 passed。
- QEMU：edu 值级 oracle 和 gpio-ftgpio010 offset/order oracle 均通过。
- paper：统计由 tools/generate_paper_results.py 从实验 JSON 自动生成。

冻结矩阵：

~~~text
19 drivers, 425 ops
314 symbolic, 64 fixed, 33 computed
71 RMW, 58 conditions, 141 registers
compile: harness=19, bare-metal=19, Linux=19
strict ready: harness=7, bare-metal=7, Linux=5
LLM synthesis ready=12
multi-source: 2 modules, 9 TUs, 5779 LoC, 166 ops, H/B/L compile=2/2
~~~

## 重要语义约束

- 不得把 fixed/computed address 计为 symbolic。
- 不得把“编译通过”写成“语义 ready”。
- switch/if 互斥 RMW 必须保留为嵌套 Ite，不能串接成顺序更新；确实无法解析时才保留 Top。
- 可精确 lowering 的 computed address 不应阻塞 readiness；含未绑定成员、宏调用或 Top 的 unsafe computed 仍必须阻塞。
- source-private state 只能中性化并输出 REHARNESS_UNSUPPORTED，不能伪造语义。
- 确定性论文实验不得调用 LLM。
- paper/generated_results.tex 是生成文件，不能手改。

## 标准验证顺序

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build
./run.sh test
python3 verification/run_matrix.py
python3 verification/run_multisource_matrix.py
verification/run_qemu_experiments.sh
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
git diff --check
~~~

## 已知限制

- 分析尚未为任意控制流维护完整的逐路径抽象存储，但常见 switch/if RMW 已能生成精确 Ite。
- computed/indexed MMIO 能保留并生成完整表达式，但含 source-private 调用或未绑定成员的地址仍不安全。
- GPIO、clock、virtio 的常见私有字段已建模；AHCI/SDHCI 等复杂 subsystem object 仍需更完整生命周期模型。
- 多源当前要求跨 TU 函数名唯一；重复 static helper 仍需 source-qualified symbol identity。
- USB host/gadget 的 callback table 与私有状态尚未完整建模，因此多源案例当前是 compile-ready 而非 strict-ready。
- 目标源文件 clang diagnostics 已从 26 降至 3；header-only frontend 差异仍报告但不污染 readiness。
- Linux 19/19 Kbuild，严格 ready 为 5/19；Harness/Bare 为 7/19。
- SVF 外部工具链成本较高，默认关闭。
- LLM synthesis 非确定性，只作为可选补全路径。

继续工作时应优先增加可验证语义覆盖，而不是通过宽松 readiness 或中性 stub 美化数字。
