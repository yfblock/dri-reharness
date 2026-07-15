# Reharness 当前维护提示

reharness 是一个面向 Linux C 驱动的 AST/RIS 提取、语义推断和多后端生成系统。继续维护时，以代码、测试和 experiments/results/*.json 为准，不要恢复历史文档中的手抄统计。

## 已完成基线

- drivers/：19 个版本化测试驱动，不是外部 symlink。
- linux/：固定 commit 的 Git submodule。
- extractor：libclang、流敏感数据流、单/多 Translation Unit 过程间内联、路径条件 RMW/Ite 变换、callback enclosing-struct 推断、access/control accounting 与 SMT path validation。
- alias：off、auto、required，默认 off；多源 manifest 使用 linked bitcode + 单次 WPA，required 模式禁止静默 fallback，并记录 SHA、工具版本和 source provenance。
- specs：.ris、.dspec、.bind、.facts。
- generators：harness、bare-metal、Linux；19/19 均编译。
- Linux：确定性 platform、PCI、GPIO/IRQ、clock provider 和 QEMU edu lifecycle；unsupported state 显式标记。
- multi-source：真实 Kbuild 模块 C67X00（4 C）、ASPEED vHub（5 C）和 DWC2（10 C）；跨 TU MMIO 传播通过，harness/bare-metal 3/3、Linux 2/3 编译。
- tests：88 passed；`./run.sh test` 首先执行 zero-shot specialization guard。
- generalization：`drivers/holdout/zero-shot-v1.json` 冻结 12 个 holdout。不得在 extractor/generator 中加入其 driver name、basename、私有前缀或 wrapper 特例。
- compile context：默认 `auto`，优先使用显式/环境指定的 `compile_commands.json`，否则读取 kernel build `.cmd`；`required` 找不到上下文必须失败，`off` 仅用于对照实验。
- clock boundary：Highbank 22 个算术基线用例通过且 3/3 mutation 类别被检出；Visconti PLL 被保守拒绝并记录 private-state 原因。
- QEMU：edu 值级 oracle 和 gpio-ftgpio010 offset/order oracle 均通过。
- paper：统计由 tools/generate_paper_results.py 从实验 JSON 自动生成。

冻结矩阵：

~~~text
19 drivers, 429 ops
317 symbolic, 73 fixed, 25 computed
69 RMW, 117 conditions, 144 registers
compile: harness=19, bare-metal=19, Linux=19
strict ready: harness=6, bare-metal=6, Linux=7
LLM synthesis ready=12
scoped RIS reliability=8/19
multi-source: 3 modules, 19 TUs, 27447 LoC, 4394 ops, H/B/L compile=3/3/2
~~~

## 重要语义约束

- 不得把 fixed/computed address 计为 symbolic。
- 不得把“编译通过”写成“语义 ready”。
- switch/if 互斥 RMW 必须保留为嵌套 Ite，不能串接成顺序更新；确实无法解析时才保留 Top。
- 可精确 lowering 的 computed address 不应阻塞 readiness；含未绑定成员、宏调用或 Top 的 unsafe computed 仍必须阻塞。
- source-private state 只有在显式、保守重绑定并通过真实后端编译验证时才能 lowering；否则必须中性化并输出 REHARNESS_UNSUPPORTED，不能伪造语义。
- readiness gate 不是语义证明；新增 ready 驱动必须额外审计真实 ID、资源规模、框架 helper 隐含 callback 和 IRQ/GPIO lifecycle，不能只检查 blocker 列表为空。
- `strict_reliable` 只针对报告声明的已识别访问/控制范围。`whole_program_complete` 只在 manifest-internal linked SVF、CFG、路径、switch、访问、computed address、value、loop、op ID/evidence 等 gate 全部通过时为真；不得把它写成整个 Linux/外部 kernel 语义证明。
- 确定性论文实验不得调用 LLM。
- paper/generated_results.tex 是生成文件，不能手改。
- holdout selection、source SHA 和 first-run case 已冻结；不能在看到结果后替换案例或缩小验收标准。

## 标准验证顺序

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
git diff --check
~~~

## 已知限制

- 分析已有显式 source-level CFG、dominance/post-dominance、join、goto/backedge 和 loop header，但尚未为任意路径维护通用 abstract-store fixpoint；前向 goto 可形成 guard，后向 goto 与未证明循环由 accounting 阻塞。
- computed/indexed MMIO 能保留并生成完整表达式，但含 source-private 调用或未绑定成员的地址仍不安全。
- GPIO、clock、virtio 的常见私有字段已建模；clock provider 可保留多 `clk_ops` 实例及 rate 算术；AHCI/SDHCI 等复杂 subsystem object 仍需更完整生命周期模型。
- 多源使用 source-qualified static symbol identity，并支持跨 TU 参数替换、MMIO 摘要传播与 manifest-level linked SVF。
- C67X00 的 HPI base/regstep/sie-number、computed address、标量宏和 helper-return 数据流已建模，生成 Linux 通过；USB host/gadget 的完整外部 lifecycle 仍未建模，因此多源案例仍不是 strict-ready。
- 目标源文件 clang diagnostics 已从 26 降至 3；header-only frontend 差异仍报告但不污染 readiness。
- `gpio-sodaville` 恢复了 0x8086:0x2e67 PCI ID、12 GPIO、native 32-bit generic GPIO dat/set/dirout 行为以及 mask/unmask/EOI fasteoi lifecycle；这也是 7/19 的新增项。
- Highbank oracle 只覆盖版本化算术公式，不代表真实硬件验证；Visconti 的拒绝边界必须保持。
- Linux 19/19 Kbuild，严格 ready 为 7/19；Harness/Bare 为 6/19。Highbank 的 Linux 专用模型不外推到通用后端。
- SVF 外部工具链成本较高，默认关闭；required 模式的多源结果必须来自 linked manifest，不能降级为逐 TU 或空 alias。
- Kbuild `.cmd` 只存在于实际构建过的 object；其余源文件需要 compile database 或先由对应 arch/Kconfig 构建产生命令。不得把 fallback include guess 写成 exact context。
- LLM synthesis 非确定性，只作为可选补全路径。

继续工作时应优先增加可验证语义覆盖，而不是通过宽松 readiness 或中性 stub 美化数字。
