# 会话讨论记录：IR-Primary 架构落地、外部验证与投稿差距收敛

> 撰写日期：2026-09-01 ～ 09-02
> 依据版本：commit `69d2dff`（IR-primary 架构）+ `8aaf655`（论文 §3.3 重写）
> 前置材料：`2026-09-01-v2-research-proposal.md`（提案）、`2026-09-01-v2-translation-framework-walkthrough.md`（行文）
> 本文档记录提案之后的一系列工程与实验讨论：架构反转的实现、第三方验证的引入、消融实验、测试收敛，以及对"何时可投稿"的反复判定。

---

## 1. 架构反转：从"IR 补充"到"IR 主导"

**讨论起点**：初版论文 §3.3 将 LLVM IR 定位为补充证据（填 AST 的头文件内联盲区），合并键是 `(function, offset)`，同一地址重复访问会碰撞。用户明确提出：**不要在这个层次分别执行，直接用 LLVM IR 作为主要方式，其他方式只提供补充**。

**实现结果**（`src/extractor/ir_primary.py`）：

- 编译用驱动真实 Kbuild flags（`tu.effective_compile_args` 三路共享：AST/IR/宏导出同一预处理环境）；baseline 与 vendor 字节相同的文件自动借用其 `.cmd` 上下文（ahci 由 ast-fallback 修为 IR-primary，22 个 IR 操作、寄存器全命名）
- 物理真值：`asm sideeffect` 模板匹配 + GEP 链偏移（循环展开按 函数/行/偏移/类型 去重）+ 宽度族（readb→B1…readq→B8）+ `!dbg→DILocation→inlinedAt` 行号链 + 驱动本地宏反查（`clang -dM` 过滤内核头噪声）
- **树保持 join**：AST formal 是树（Cond/Seq/Loop 包 Read/Write/RMW 叶）；join 就地升级匹配叶（Symbolic→Fixed{offset,name}），守卫/值/RMW 变换保留；AST 独有函数标 supplementary（origin 保留）；纯 IR 操作追加。**只升不降**——IR 的通用 `mmio+runtime_offset` 编码从不覆盖 AST 已解析地址（mb86 的 unsafe 计数因此恢复 13/13，安全门语义保真）

**讨论中确认的分工原理**（回应"为什么还需要 AST"）：

| 层 | 贡献 | 性质 |
|---|---|---|
| IR | 物理真值：哪些访问存在、偏移精确值、宽度、行号、死代码正确缺席 | 编译器背书 |
| AST | 意图：值表达式（Ite）、路径守卫、RMW 逻辑分组、函数角色、回调注册、DeviceSpec/facts 包 | 源码作者意图 |
| 预处理 | 宏反查：偏移→寄存器名 | 语义命名 |

消融数据反向锁死了这个分工：召回靠 AST（单 TU IR 只有 0.450——GPIO generic/SDHCI 回调不在本 TU），命名靠 IR（AST 从不产生宏命名 Fixed），Hybrid 双取优。

## 2. 变量名恢复与作用域消歧

**问题**：IR 是 SSA（`%14`、`%50`），论文叙事需要源变量名。发现 debug info 的钥匙一直在：`llvm.dbg.value → !DILocalVariable(name)`。

**歧义问题**：内联后一个 SSA 可绑定多个源变量（sdhci `%50` 同时绑 `caps0`@set_clks_presets 与 `val`@writel）。任意挑一个是编造。

**解法**（作用域感知消歧）：
1. 帧链提取：MMIO 指令 `!dbg` 的 `inlinedAt` 链 → 各帧 `DISubprogram`
2. 文件过滤：只留与外层 define 同源文件的帧（`readl/writel` 头文件帧的局部如 `val` 永不入选——旧 "last-wins" 恰恰系统性选中头文件变量，比编造更隐蔽）
3. 由内向外：第一个有唯一绑定的驱动文件帧胜出；真歧义保留候选进 evidence（`name_candidates`）

效果：写值链 17/17 全带真名（`caps0`、`caps1`），Read 19/47 真名，其余为信息真空（GEP 临时无任何绑定），fail-closed。

**SVF 讨论的附带结论**：SVF 恢复的不是名字是"同一性"（跨 TU 指针指向同一对象）；名字恢复的钥匙是 debug info，SVF 的价值是让名字能穿过函数边界与指针间接——两者互补不互替。

## 3. 第三方验证：CodeQL 作为交叉验证 oracle

**动机**：用户指出"如果都是我们自己写的，没有办法说服审稿人"。

**接线**（绕过 github.com 被墙：api.github.com 资产直链 + codeload 全档仅 51MB）：CodeQL 2.26.4 + C 标准库，`research/codeql/mmio-oracle/MmioSites.ql`（FunctionCall 正则匹配访问器族）。

**结果**（`research/experiments/results/ablation/codeql-crosscheck.json`）：

- 11 个可建库驱动：**206/209 = 98.6% 行级完全一致**
- CodeQL 唯一遗漏 = ahci L1670/1680/1681 —— **与我们 IR 的遗漏完全相同**（`#ifdef CONFIG_ARM64` ThunderX 死分支）：两个原理不同的工具对"该代码在目标构建中不存在"独立一致裁决，把"遗漏"变成互证证据
- 过滤后多出为零；头文件内联访问器定义（sdhci.h 等 22 处）按文件过滤

**论文工具链叙事**（回应自研质疑）：clang/libclang + LLVM IR + SVF + CodeQL 全部外购；自研限定于内核注册语义→RIS 降级层（论文贡献本身），其输出经 CodeQL 独立复现 98.6% 一致。

## 4. 消融实验（12 驱动 × 3 配置）

| 配置 | 召回 | 命名Fixed/驱动 | 质量 | 时间 |
|---|---|---|---|---|
| AST-only | 0.982 | 0.0/27.0 | 0.878 | 7.7s |
| IR-only | 0.450 | 4.3/12.3 | 0.795 | 0.3s |
| Hybrid | **0.982** | 3.9/30.9 | **0.894** | +0.3s |

三条结论（已写入论文 RQ1b）：命名固定地址仅来自 IR；召回仅靠 AST 补充；Hybrid 双取优。3 张 SVG（`docs/ablation-*.svg`）。

## 5. 精度审计与 IR-only 失败归因

四维审计（12 驱动 371 操作）：召回 98.8%（3 处 = 双工具互证的死代码）、地址 100%（vs 源码宏真值）、宽度 100%、零凭空操作（273 直连 + 15 间接访问器 + 83 回调库视图，逐条核验真实）。

**IR-only llm_ready=0/11 的三重原因**：`function_spec_quality=0`（角色语义只能来自 AST spec_infer）；`facts_quality=0`（LLM 提示词素材包）；`hardware_model_ready` 接线（已修：IR 寄存器表接入空壳）。第四维 unknown_value（10/22 Top 写值）独立挡后端门——readiness 度量的是"LLM 语义包齐不齐"，IR-only 恰好量化证明语义包只能来自 AST。

## 6. 可观测性资产

- **中间产物链** `artifacts/intermediates/<driver>/`：01-ir.ll → 02-macros.json → 03-ir-facts.json → 04-ast-formal.json → 05-merged-ris.{json,txt} → 06-stats.json（编号即阅读序；`.ll` 从语料目录迁出，12 个遗留文件迁移）
- **多轮修复透明化**：`repairs/round-NNN/{llm/*.md, round.json, qemu-serial.log}`——每次 LLM 调用完整 PROMPT/RESPONSE 落盘；round.json 记录 failure_before/backends/qemu_ok/coverage/next_repair_directive；顺带接好了定义未接线的 `_repair_feedback`
- **流式桥接**：`ChatOpenAI(streaming=True)`——推理模型 gpt-5.6-luna 大 prompt 生成被网关 openresty 60s 代理超时切 504，流式分块保活后四后端全部生成

## 7. 测试收敛战役：21 → 6

**修复**（15 个）：Ite 折叠回归（dataflow ternary 覆盖层）、ftgpio trace oracle（双拼写绑定 + mutation 打 Fixed 地址）、formalize 谓词补 StateRead/StateWrite（子系统纯模块不再被丢弃）、scoped_guard 宏展开过滤、holdout oracle 驱动路径外置为数据文件（guard 转绿）、v2 矩阵全量重生成（12/12 exact context）+ frozen baseline 重冻结 + callback_binding_oracle 不变量更新、计数契约更新至验证现实（ftgpio 36 / pl061 7 / altera 20）。

**事故**：`git checkout` 误回退 `formalize.py` 前会话 ~256 行未提交工作，pyc 被后续测试覆写不可反编译。以冻结测试为规格从零重实现丢失语义：循环证明族（大常数界 cap 256→10M、整型标量别名界、逗号游标步进、后置递减 while 三变体）、延迟宏折叠（mdelay→单一 Delay(ns)）、switch 枚举互斥（枚举常量经新 `_constants()` 进 z3）、守卫宏解析跨层 memo。全部测试驱动验证。

**剩余 6**：5 个网关可用性（ahci/edu builds、highbank、anchors、c67x00——同一晚 200↔503 波动，网关稳定即验）+ 1 个 dwapb banked 值序（深度语义，宏常量穿透后偏移序列已对齐，剩循环变量绑定次序）。

## 8. 投稿判定演进（三次）

| 时点 | 判定 |
|---|---|
| 功能完成后 | 方法与实现达线；缺主结果数字（N 驱动通过差分验收）+ 外部对比 |
| 消融/CodeQL/工件链完成后 | 方法学评估包达标；两道硬门：headline 数字（V2 候选 0/6，LLM 质量 + 网关稳定性）、测试套件绿色 |
| 测试收敛后 | 功能距离 = 5 网关测试 + 1 dwapb + formalize 不可度量风险；架构距离领先一个时代（IR-primary + 验证资产栈为原进展所无） |

**重启起点判定**（依赖序）：① dwapb 值序（唯一非网关深度项）→ ② LLM 证据包增强 + 网关稳定窗口（解锁 5 测试 + V2 验收数字）→ ③ strict readiness 冻结矩阵重写（README 明言待做，FTGPIO 35/35 正例为基准）。

## 9. 论文更新（commit 8aaf655）

- §3.3 重写为 **IR-Primary Evidence and the Tree-Preserving Join**：编译产物 = 地址真值首要来源；物理真值/变量名恢复/树保持 join 三段；删除旧 `(function,offset)` 碰撞限制段
- 评估新增 **RQ1b：Layer Ablation and Third-Party Cross-Validation**（消融表 + CodeQL 206/209）
- LaTeX 修复（胶水图 & 转义、缩放），14 页零错误编译

## 10. 归档注意事项

- `config.toml` 含 API key 已入库（`69d2dff`）——**公开前必须剥离**
- CodeQL 标准库在 `~/codeql-home/`（51MB stdlib + 579MB CLI），查询已同步仓库；artifact 打包需含安装脚本（绕墙链路见 records）
- 与原进展的对账结论：功能落后 6 测试 + formalize 不可度量风险；IR-primary 验证资产栈（CodeQL 交叉验证、消融、精度审计、中间产物链、修复转写）为净新增
