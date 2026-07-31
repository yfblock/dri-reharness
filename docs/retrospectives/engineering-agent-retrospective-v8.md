# Engineering-agent retrospective v8

> 范围：在 `paper-artifact-v7` 基础上，实现 manifest-level linked SVF、显式 source CFG、C67X00 HPI source-private state 与差分/mutation oracle，并重新封存全部确定性结果。

## 1. 最终结果

- 实现提交：`85c576862274f5062cfdf956692be20a6a20b3c4`。
- 回归测试：83/83。
- 单源编译：harness、bare-metal、Linux 均为 19/19。
- strict readiness：harness 6/19、bare-metal 6/19、Linux 7/19。
- multi-source：19 TU / 27,447 LoC；harness/bare-metal 3/3，Linux 2/3，原始 Kbuild 3/3。
- C67X00：三后端编译；32/32 computed HPI address 可 lowering。
- linked SVF：C67X00 required run 成功链接 4 TU，linked-bitcode SHA-256 为 `f0748140aa0b2e2ee43f95596ba461732148052b7b8841453696f142028388c2`。
- C67X00 oracle：5 个 primitive、4 个 original-C↔RIS differential case 通过，4 类 mutation 全被检出。
- QEMU：EDU 值级 oracle 与 FTGPIO probe offset/order oracle 通过。

## 2. 本阶段增加的机制

### 2.1 Manifest-level linked SVF

多源分析不再对每个 TU 独立运行 SVF。每个源文件先按自己的编译上下文生成 bitcode，然后由 `llvm-link` 合并，再生成一次 IR stub 并执行一次 WPA。结果记录：

- linked bitcode SHA-256；
- translation unit 数与 source provenance；
- clang、llvm-as、llvm-link、WPA 路径和版本；
- accepted/rejected alias candidate；
- `linked_alias_complete` 与 failure diagnostics。

`required` 模式在工具缺失、编译、链接或 WPA 失败时直接失败，不允许退回逐 TU 或空 alias。debug prefix map 消除了临时目录路径，使 linked SHA 可复现。

### 2.2 可审计的 whole-program gate

`whole_program_complete` 不再是固定 false，而是以下 gate 的合取：linked analysis、全部 TU、bitcode hash、internal call resolution、access accounting、CFG、path validation、switch exclusivity、唯一 op ID、evidence、computed address、value、loop 与 access domain。

其 claim scope 明确为 `manifest-internal`。即使该字段为 true，也不代表外部 kernel、USB core 或真实硬件协议已被证明。

### 2.3 显式 source-level CFG

CFG 记录 block、pred/succ、immediate dominator/post-dominator、join、goto edge、backedge、loop header 与 unresolved transfer。可界定的前向 goto 被 lowering 为路径 guard；后向 goto（包括 `err_*` cleanup label）仍保守阻塞。

### 2.4 C67X00 HPI 建模

C67X00 的核心问题不是普通 pointer alias，而是 `struct c67x00_hpi` 中的动态 state。实现把以下字段转为显式 source-private state：

- `hpi.base`
- `hpi.regstep`
- `sie_num`

生成地址保持为 `base + HPI_ADDR * g->hpi_regstep`，不再退化为 `0 + HPI_* * 0`。Linux backend 从 `hpi-regstep` 和 `sie-number` 属性绑定状态，并保留安全的 driver-local scalar function macro。helper-return LHS 传播也被修复，使 read→transform→write 的值链不会丢失。

## 3. 过程中遇到的问题

### 3.1 接口中间态破坏

linked SVF 改造跨越 extractor、cache、formalization 和 CLI。中途若只更新生产者或消费者一侧，测试会出现大量与目标无关的 schema/字段失败。大模型倾向于一次修改多个层次，但无法天然保证每个中间提交都可运行。

教训是先确定新旧接口的兼容窗口，再按可测试切片推进；不能依赖模型在长上下文中记住所有调用点。

### 3.2 相对头文件丢失

逐 TU bitcode 编译初版没有完整复现源文件自己的 include working directory，C67X00 的相对头文件解析失败。AST 能解析并不意味着另一个 clang invocation 自动继承同一上下文。

修复后每个 TU 都从 manifest/source provenance 恢复独立编译上下文。

### 3.3 临时 debug path 使 hash 不稳定

linked bitcode 虽然语义相同，但 DWARF/debug metadata 包含随机临时目录，导致每次 SHA-256 不同。仅固定源文件顺序不足以得到可复现 artifact。

最终在 bitcode 编译时加入 debug prefix mapping，消除临时根路径。可复现性需要检查二进制 provenance，而不只是算法确定性。

### 3.4 函数宏过度泛化破坏 Visconti PLL

为了保留 C67X00 的 `SOFEOP_*`、`SIEMSG_*` 标量宏，初版把更多 function macro 直接重放到 backend。Visconti 的 macro 含 aggregate member access，生成代码缺少原结构体上下文，导致三后端编译失败。

最终只允许不含 `->` 或 aggregate member 的 portable scalar macro。这个回退说明：一个案例需要的语法保真不能自动外推为通用可移植语义。

### 3.5 CFG cleanup guard 破坏 Cadence readiness

probe 中资源获取失败后跳到 cleanup label。CFG 正确地保留了 forward-goto guard，但 backend 又把它当作运行时 source-private 条件；生成环境已经通过 DeviceSpec 绑定成功路径，重复 guard 反而使 `gpio-cadence` 掉出 strict-ready。

修复是在 FormalRIS/CFG 中保留完整证据，只在资源已经绑定的 backend probe 成功路径折叠 cleanup guard。分析证据与生成执行前提不能混为一层。

### 3.6 `err_*` 标签启发式会隐藏真实 backward goto

仅凭 cleanup label 名称豁免控制流，会把后向跳转错误当成安全退出。最终删除名称启发式，按 CFG edge 方向和可证明边界判定。名字不是控制流证明。

### 3.7 RMW 指标变化不是自动回退

修复 helper-return LHS 后，更多真实 declaration assignment 进入值链，部分 operation 分类与 RMW 聚合发生变化。固定期待旧数字会把语义改进误判为回退。

正确做法是逐项核对 source evidence、生成 trace 和 mutation，而不是把历史 aggregate 当作不可变化的目标函数。

### 3.8 交接命令覆盖了负边界结果

交接摘要建议把 `clock_arithmetic_oracle.py` 直接输出到 `clock-model-boundary.json`，这会覆盖 Visconti source-model rejection，只留下 Highbank 算术结果。最终通过检查 JSON schema 发现并改用 `run_clock_model_boundary.py` 重建组合报告。

这也是模型协作的边界：结构化交接仍可能包含看似合理但会破坏 artifact 语义的命令，后继模型必须验证输出内容，不能机械执行。

## 4. 大模型能力观察

### 4.1 表现较强的部分

- 能跨 AST、bitcode、SVF、CFG、RIS 与三个 backend 建立一致的数据链；
- 能从 C67X00 失败中识别 aggregate source-private state，而不是盲目增加 alias；
- 能构造 original-C↔RIS differential oracle，并选择 register index、stride、wrapper target、order 等高价值 mutation；
- 能在目标数字已经达到后继续跑完整 19-driver、多源、QEMU 和论文构建；
- 能接受 C67X00 “编译成功但 strict 不通过”、Aspeed “保留 Linux 负边界”的非对称结果。

### 4.2 明显能力边界

- 大范围接口修改容易留下短暂不一致，模型对跨文件隐含契约没有形式保证；
- 容易从一个成功案例过度泛化，例如把 C67 标量宏规则扩展到 Visconti aggregate macro；
- 容易把分析层证据直接下沉为 backend runtime guard，忽略生成环境已经建立的前置条件；
- 对 label 名称、AST 形状等表面模式有启发式依赖，必须用反例压制；
- 聚合指标变化会诱导模型围绕旧数字修补，而不是先验证 source-level 语义；
- 交接摘要和模型生成的执行命令本身也必须接受 schema、负例和最终 artifact 审计。

## 5. 当前真实边界

- linked SVF 覆盖 manifest 内部 bitcode 和 pointer analysis，不覆盖外部 kernel module、动态注册和硬件状态机。
- C67X00 的 HPI register addressing 已有差分/mutation 证据，但完整 HCD/USB core lifecycle 未建模。
- CFG 是显式且可审计的，但尚无任意路径 abstract-store fixpoint、递归摘要和一般 loop widening。
- `whole_program_complete` 的 true 只意味着所有声明 gate 在 `manifest-internal` scope 内通过。
- Aspeed vHub 生成 Linux 仍失败；不能用 C67/DWC2 的成功外推 USB gadget endpoint lifecycle。
- QEMU 仍只覆盖 EDU 与 FTGPIO；Highbank、Visconti、C67X00、DWC2 和 Aspeed 没有真实设备级运行时等价证明。

## 6. 结论

本阶段的研究价值不只是把 multi-source Linux 从 1/3 提升到 2/3，而是建立了更严格的 linked analysis provenance、CFG/whole-program gate 和 C67X00 差分证据。

同样重要的是，模型在过程中真实地产生了两类跨案例回退：function macro 过度泛化破坏 Visconti，CFG guard 破坏 Cadence readiness。它们都无法靠模型自信或单个目标案例发现，只能由全量矩阵、负例、mutation、源码审计和机器结果 schema 共同暴露。这些外部约束定义了当前大模型作为工程代理的可靠能力边界。
