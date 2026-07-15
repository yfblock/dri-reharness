# Reharness 当前维护提示

reharness 是一个面向 Linux C 驱动的 AST/RIS 提取、语义推断和多后端生成系统。继续维护时，以代码、测试和 experiments/results/*.json 为准，不要恢复历史文档中的手抄统计。

## 已完成基线

- drivers/：19 个版本化测试驱动，不是外部 symlink。
- linux/：固定 commit 的 Git submodule。
- extractor：libclang、流敏感数据流、单/多 Translation Unit 过程间内联、路径条件 RMW/Ite 变换、callback enclosing-struct 推断、access/control accounting 与 SMT path validation。
- alias：off、auto、required，默认 off，SVF 为可选增强。
- specs：.ris、.dspec、.bind、.facts。
- generators：harness、bare-metal、Linux；19/19 均编译。
- Linux：确定性 platform、PCI、GPIO/IRQ、clock provider 和 QEMU edu lifecycle；unsupported state 显式标记。
- multi-source：真实 Kbuild 模块 C67X00（4 C）、ASPEED vHub（5 C）和 DWC2（10 C）；跨 TU MMIO 传播通过，harness/bare-metal 3/3、Linux 1/3 编译。
- tests：78 passed。
- clock boundary：Highbank 22 个算术基线用例通过且 3/3 mutation 类别被检出；Visconti PLL 被保守拒绝并记录 private-state 原因。
- QEMU：edu 值级 oracle 和 gpio-ftgpio010 offset/order oracle 均通过。
- paper：统计由 tools/generate_paper_results.py 从实验 JSON 自动生成。

冻结矩阵：

~~~text
19 drivers, 429 ops
317 symbolic, 73 fixed, 25 computed
69 RMW, 70 conditions, 144 registers
compile: harness=19, bare-metal=19, Linux=19
strict ready: harness=6, bare-metal=6, Linux=7
LLM synthesis ready=12
scoped RIS reliability=8/19, whole_program_complete=false
multi-source: 3 modules, 19 TUs, 27447 LoC, 4394 ops, H/B/L compile=3/3/1
~~~

## 重要语义约束

- 不得把 fixed/computed address 计为 symbolic。
- 不得把“编译通过”写成“语义 ready”。
- switch/if 互斥 RMW 必须保留为嵌套 Ite，不能串接成顺序更新；确实无法解析时才保留 Top。
- 可精确 lowering 的 computed address 不应阻塞 readiness；含未绑定成员、宏调用或 Top 的 unsafe computed 仍必须阻塞。
- source-private state 只有在显式、保守重绑定并通过真实后端编译验证时才能 lowering；否则必须中性化并输出 REHARNESS_UNSUPPORTED，不能伪造语义。
- readiness gate 不是语义证明；新增 ready 驱动必须额外审计真实 ID、资源规模、框架 helper 隐含 callback 和 IRQ/GPIO lifecycle，不能只检查 blocker 列表为空。
- `strict_reliable` 只针对报告声明的已识别访问/结构化控制流范围；不得写成 whole-program 完整证明。
- 确定性论文实验不得调用 LLM。
- paper/generated_results.tex 是生成文件，不能手改。

## 标准验证顺序

~~~bash
git submodule update --init
./tools/prepare_kernel.sh build
./run.sh test
python3 verification/run_matrix.py
python3 verification/run_multisource_matrix.py
python3 verification/run_clock_model_boundary.py
verification/run_qemu_experiments.sh
python3 verification/reliability_report.py --output experiments/results/reliability.json
python3 verification/ris_mutation_oracle.py
python3 verification/ris_trace_oracle.py
python3 verification/ftgpio_trace_oracle.py
python3 tools/generate_paper_results.py
(cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex)
git diff --check
~~~

## 已知限制

- 分析尚未为任意控制流维护完整 CFG fixpoint，但常见 switch/if RMW、参数型 early exit 和静态有界规范循环已有显式模型；其余控制流由 accounting 阻塞。
- computed/indexed MMIO 能保留并生成完整表达式，但含 source-private 调用或未绑定成员的地址仍不安全。
- GPIO、clock、virtio 的常见私有字段已建模；clock provider 可保留多 `clk_ops` 实例及 rate 算术；AHCI/SDHCI 等复杂 subsystem object 仍需更完整生命周期模型。
- 多源使用 source-qualified static symbol identity，并支持跨 TU 参数替换和 MMIO 摘要传播。
- USB host/gadget 的 callback table 与私有状态尚未完整建模，因此多源案例当前是 compile-ready 而非 strict-ready。
- 目标源文件 clang diagnostics 已从 26 降至 3；header-only frontend 差异仍报告但不污染 readiness。
- `gpio-sodaville` 恢复了 0x8086:0x2e67 PCI ID、12 GPIO、native 32-bit generic GPIO dat/set/dirout 行为以及 mask/unmask/EOI fasteoi lifecycle；这也是 7/19 的新增项。
- Highbank oracle 只覆盖版本化算术公式，不代表真实硬件验证；Visconti 的拒绝边界必须保持。
- Linux 19/19 Kbuild，严格 ready 为 7/19；Harness/Bare 为 6/19。Highbank 的 Linux 专用模型不外推到通用后端。
- SVF 外部工具链成本较高，默认关闭。
- LLM synthesis 非确定性，只作为可选补全路径。

继续工作时应优先增加可验证语义覆盖，而不是通过宽松 readiness 或中性 stub 美化数字。
