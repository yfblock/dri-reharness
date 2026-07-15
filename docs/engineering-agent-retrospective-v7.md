# Engineering-agent retrospective v7

> 范围：在 `paper-artifact-v6` 基础上，为 RIS 增加可审计可靠性机制，并重新验证 19-driver、multi-source、clock boundary、mutation、differential trace 与 QEMU。

## 1. 最终结果

- 实现提交：`e3e1d48bd677c08e58dfc51bdd206bad3c226560`。
- 回归测试：78/78。
- 单源编译：harness、bare-metal、Linux 均为 19/19。
- strict readiness：harness 6/19、bare-metal 6/19、Linux 7/19。
- 机器可靠性报告：scoped strict 8/19；报告固定声明 `whole_program_complete=false`。
- multi-source：19 TU / 27,447 LoC，harness/bare-metal 3/3，Linux 1/3，原始 Kbuild 3/3。
- mutation：寄存器偏移、访问宽度、RMW operator、branch predicate 4/4 被抓获。
- differential trace：synthetic path-state 与真实 FTGPIO callback 均匹配，mutated RIS 均被抓获。
- QEMU：EDU 值级 oracle、FTGPIO probe offset/order oracle 均通过。

## 2. 新增可靠性机制

### 2.1 Source-to-RIS accounting

每个已识别 source access site 都有稳定 `site_id`。每个 RIS leaf 记录：

- `op_id`
- source evidence
- reliability
- address/value/path precision
- access domain

已知 MMIO/regmap API、直接 volatile 解引用和源码 inline asm 都进入 accounting。unsupported、filtered、unaccounted 或无 evidence 的操作阻止 strict completion。

### 2.2 控制流与路径

- switch case/default 互斥 guard；
- Z3 可满足性和 switch pair exclusivity；
- 参数型 early exit 转成 continuation guard；
- canonical statically bounded `for` loop 可证明并 lowering；
- goto、寄存器相关 loop break/continue 进入 control accounting；
- 正常 return 后的 framework cleanup block 标为 `intentionally_unreachable`，与真正矛盾路径分开。

### 2.3 调用与别名

- 自动简单 MMIO wrapper summary；
- 静态 ops table 间接调用解析；
- callback entry 与 direct helper 的模块边界分离；
- SVF required/auto 真正执行，记录版本、候选、接受/拒绝原因和 alias provenance。

### 2.4 动态与反向证据

- RIS semantic mutation oracle；
- 原始 synthetic C 对 RIS interpreter 的差分 trace；
- 从真实 FTGPIO AST 取得原 callback 源码，编译后与 RIS trace 比较；
- Highbank 算术 oracle 与 Visconti 负面泛化边界；
- EDU 与 FTGPIO QEMU。

## 3. 过程中遇到的主要问题

### 3.1 工作区入口并不是真实 Git 根目录

会话 cwd 的 `.git/` 是空挂载，真实仓库在 `reharness/`。第一次 `git status` 返回 “not a git repository”。模型必须先核对 `pwd`、目录布局和 Git 元数据，不能因为环境上下文写着某个 cwd 就假设它是仓库根。

### 3.2 自动 wrapper 传播过度内联 callback

初版把已注册 `.irq_ack` callback 又内联进 `set_irq_type`，造成同一 FTGPIO source site 发射两次；PL061 的 PM callback 也重复获得 GPIO callback 的 computed accesses。结果是 10 个回归同时出现。

修复不是简单去重，而是区分：

- direct call 到 callback entry：保持独立入口，不传播；
- 真实 ops-table indirect dispatch：必须传播目标语义。

这说明“更多过程间传播”不是单调改进；入口边界本身是语义。

### 3.3 wrapper 假阳性：DMA memory barrier 被当成 MMIO

ASPEED vHub 的 `vhub_dma_workaround(void *addr)` 使用 `__raw_readl((void __iomem *)addr)` 强制普通 DMA memory ordering。初版 wrapper inference 仅看到 raw read，就增加了 13 个虚假的 device-register operations。

修复要求 wrapper address 具有更强 provenance：显式 MMIO base 命名、iomem 类型或 aggregate base/regs 字段。一个局部 cast 不能证明设备 MMIO。

### 3.4 普通赋值传播把未知 helper 当成精确表达式

`deb_div = DIV_ROUND_CLOSEST(...)` 被直接替换进后续 write value，虽然数据流分析并没有该 helper 的语义 summary。这导致 Linux source-private normalization 把原本可绑定的局部变量改成 unsupported call。

修复后仅传播显式允许的表达式宏；任意 helper call 保持局部符号。这里的能力边界是：语法可见不等于语义已知。

### 3.5 loop initializer 被错误冻结

初版 general assignment store 把 loop 内 `i = 0` 合成为 `i < 4 ? 0 : i`，使 loop body 的 write value 永远趋向 0。问题来自把词法赋值合并误当成 loop fixpoint。

修复是完全不把 loop-carried assignment写入普通 scalar store；induction semantics 只由已证明的 Formal Loop 表达。

### 3.6 early-return 建模范围过宽

初版把 probe 中 `if (IS_ERR(base)) return` 等 framework error checks 都变成生成 harness 的条件。通用 harness 没有构造这些框架状态，默认值使整个成功路径被跳过，FTGPIO trace 从 4 个 op 变成 0。

最终只对由 callback 参数和常量组成、且无需 pointer dereference 的条件做 continuation proof。资源获取失败路径作为入口前置假设/cleanup scope 记录，而不是伪装成一般 CFG。

### 3.7 宏展开造成 inline asm 与 goto/break 假阳性

`WARN_ON`/`BUG_ON` 的内部实现包含 asm cursor；`scoped_guard` 宏展开包含 synthetic goto/break。若只按 libclang cursor kind 分类，会把它们当成驱动源码的硬件 asm 与控制转移。

修复要求 source spelling 仍显式包含 `asm`，并过滤已知 scoped-guard expansion。AST kind 需要与用户可见源码 provenance 联合解释。

### 3.8 静态 7/19 不等于真实 backend 7/19

中途 machine report 达到 scoped strict 7/19，但完整矩阵只有 Linux-ready 5/19：

- EDU 的 pointer guard 使通用 generator 产生无效 `*off`；
- Highbank 的 Linux source model 成功，但评分错误地要求先通过 bare-metal。

最终：

- pointer-dereference guard 不进入通用 continuation proof；
- Linux readiness 在实际 generated artifact 编译、语法、TODO/unsupported 均通过时，可独立于 generic backend readiness；
- Highbank 因此 Linux-ready，但 harness/bare-metal 仍为 false。

这是本阶段最重要的过程教训：必须运行实际 backend pipeline，不能用静态 score 自证。

### 3.9 可靠性增强使 multi-source headline 下降

旧文档写 multi-source 三后端 3/3 编译。新 accounting/path/control 机制后：

- harness/bare-metal 仍 3/3；
- Linux 只有 DWC2 通过；
- ASPEED vHub 与 C67X00 保留明确 unsupported 和 dynamic/control blockers。

这不是应被“修平”的数字回归。旧结果部分依赖静默归一化或缺少 blocker；新结果更接近真实能力边界。论文和 README 必须同步下降，而不是维护旧 headline。

## 4. 大模型在过程中的行为

### 4.1 较强能力

- 能从 10 个表面不同的测试失败归纳出 callback boundary 和 wrapper inference 两个共同根因；
- 能构造接受样本、拒绝样本、mutation 与 differential oracle；
- 能在达到目标数字后继续检查实际 backend，而不是只停在 score；
- 能接受负面结果并更新论文 claim，例如 multi-source Linux 从 3/3 降为 1/3；
- 能通过 Highbank/Visconti 正负对照表达泛化边界。

### 4.2 明显风险

- 倾向于把“更多传播/更多路径条件”先视为能力提升，直到回归测试揭示入口边界和 framework precondition；
- 容易把 AST cursor kind 当成源码语义，忽略宏 expansion provenance；
- 容易围绕 7/19 优化静态 gate，而不是第一时间区分 scoped assurance、generic backend 和 Linux-specific lowering；
- 会生成过宽的初版机制，然后依赖回归逐步收紧；若测试语料不足，这类假阳性可能直接进入 artifact；
- 文档中的旧数字不会自动失效，必须从 JSON 重新生成并全文搜索手抄结论。

## 5. 当前能力边界

### 5.1 不是 whole-program 完整追踪

- SVF 是逐 translation unit 执行，不是 linked whole-program bitcode；
- 间接调用只覆盖简单静态 initializer/assignment；
- 未知外部 wrapper、复杂 function-pointer mutation、动态注册仍可能超出范围；
- reliability report 因此固定 `whole_program_complete=false`。

### 5.2 不是完整符号执行

- 没有一般 CFG fixpoint、loop widening、递归摘要或 arbitrary goto state merge；
- bounded canonical loop、switch、简单 early exit 是受限结构化模型；
- hardware polling loop 对 generic backend 仍是 conservative。

### 5.3 runtime oracle 覆盖有限

- EDU 有值级设备 oracle；
- FTGPIO 只覆盖 probe 与一个真实 callback 的 trace；
- Highbank 是算术 oracle，不是真实时钟硬件；
- Sodaville、Visconti 和 multi-source USB 没有对应设备级运行时模型。

## 6. 后续建议

1. linked multi-TU bitcode + SVF，并把 alias scope 写入 cache/provenance；
2. 为 CFG 建立基本块、dominance、return/goto merge 和 loop summary，而不是继续扩充词法特例；
3. 对 direct volatile access 实现正式 lowering，而不仅是 unsupported accounting；
4. 对每个新 wrapper/access domain 同时增加正例、反例和 mutation；
5. 将 reliability report 纳入 CI，并要求 `claim_scope` 与 headline claim 一致；
6. 为 multi-source USB 建立 subsystem lifecycle oracle，再恢复 Linux compile/readiness headline。

## 7. 结论

本阶段最大的进展不是把数字推到 7/19，而是把“为什么能相信这个 7”拆成可审计 evidence、mutation、SMT、backend compile 和 runtime oracle，并把未覆盖范围机器可读地声明出来。

同样重要的是，模型在过程中多次产生过度泛化：callback 重复内联、DMA read 假 MMIO、framework error path 过度路径化、宏 asm/goto 假阳性。可靠性来自回归、负例、实际 backend 和运行时证据共同约束模型，而不是来自模型第一次给出的实现或自信判断。
