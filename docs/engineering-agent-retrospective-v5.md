# 大模型工程代理能力边界：reharness v4→v5 实测复盘

> - 日期：2026-07-15
> - 范围：Codex 作为仓库工程代理，从 `paper-artifact-v4` 继续提升 strict readiness，并封存、推送 `paper-artifact-v5`。
> - 相关实现：`2d3736a feat: model GPIO and clock source-private callbacks`
> - 冻结版本：`11e3564 chore: freeze strict-readiness artifact v5` / `paper-artifact-v5`

本文讨论的是“大模型作为长期工程代理”的能力边界。大模型直接合成 Linux 驱动时出现的 DMA/IRQ 约束失守、内核 API 漂移、跨函数不一致、输出格式不稳定等问题，另见 [llm-limitations.md](llm-limitations.md)。两类场景必须区分：

- **代码合成器**：模型直接产出候选驱动，主要风险是生成代码本身不可靠。
- **工程代理**：模型搜索、诊断、修改、运行验证、维护 Git 和论文制品，主要风险是错误假设、验证覆盖不足和长任务状态漂移。

## 1. 本次任务与实际结果

任务起点是 v4 冻结结果：19/19 驱动三个后端均可编译，但 Linux strict readiness 只有 4/19。计划是先解锁 `gpio-idt3243x`，再把同类建模推广到 `clk-highbank`。

最终结果：

- `gpio-idt3243x` 达到 Linux strict readiness：动态 `girq->init_hw` 被正确识别为 `gpio_irq_chip.init_hw`。
- `clk-highbank` 达到 Linux strict readiness：保留四个不同的 `clk_ops` 实例、PLL/分频算术、纯 helper、父时钟/provider 注册和 OF 变体。
- Linux strict readiness 从 4/19 提升到 6/19；harness、bare-metal、Linux 均为 6/19 strict-ready。
- 测试从 54 增加到 55，结果为 `55 passed, 0 failed`。
- 单源矩阵仍为 19/19 三后端编译。
- 多源矩阵保持 223/223 跨 TU 调用边解析，三个案例三后端和 original Kbuild 均成功；这里的 original Kbuild success 仍是已记录的 USB 外部符号 warning retry，`strict_success=false`。
- QEMU 保持 `EDU_TRACE_OK` 和 `TRACE_MATCH_OK`。
- 论文 PDF 成功构建，v5 提交和标签成功推送到 GitHub。

权威证据：

- `experiments/results/matrix.json`
- `experiments/results/multisource-matrix.json`
- `experiments/results/qemu.json`
- `paper/generated_results.tex`
- `paper/paper.pdf`
- Git 提交 `2d3736a`、`11e3564` 和标签 `paper-artifact-v5`

## 2. 工程过程中遇到的问题

### 2.1 仓库根目录与上下文摘要不一致

会话环境给出的工作目录是 `dri-trans-paper`，但顶层 `.git` 只是空目录，真正的仓库是嵌套的 `reharness/`。模型第一次直接执行 `git status` 得到：

```text
fatal: not a git repository (or any of the parent directories): .git
```

随后通过 `pwd`、`ls -la` 和查找 `.git` 才定位到真实仓库。

这说明：即使上一个模型留下了较完整的状态摘要，工程代理也不能把摘要或环境声明当作当前文件系统事实。仓库根、HEAD、dirty state 和 submodule 状态都必须重新探测。

### 2.2 文档和冻结结果发生漂移

v4 审计时发现 `REPRO.md` 仍写着 strict readiness `7/7/5`，而权威矩阵和生成论文数据实际是 `6/6/4`。后续又发现：

- `README.md` 仍写 `7/7/5`；
- `PROMPT.md` 仍写旧测试数和旧多源规模；
- `paper.tex` 对 Clock state 的描述仍是“源码提到 clk 就添加 ClockResource”，与修正后的资源识别不一致。

模型能够通过交叉检查发现这些问题，但不是一次性全部发现：先修正 `REPRO.md`，在 v5 完成后再次全文搜索才清理 README、PROMPT 和论文叙述。

这暴露出长任务中的典型风险：**代码、机器结果、维护提示和论文叙述是四套不同状态，局部验证不能保证全局一致。**

### 2.3 对 JSON schema 做了过早假设

模型最初假设结果 JSON 顶层包含 `summary`、`metadata`、`cases`，`jq` 查询失败：

```text
jq: error: Cannot iterate over null
```

之后先查询 `keys` 和字段类型，才改用真实的 `aggregate`、`drivers`、`environment` schema。

这类错误没有修改数据，但说明模型会依据常见命名模式补全未知结构。对于实验制品、数据库和 API，正确顺序应是“先枚举 schema，再写查询”，不能依赖语言模型的命名先验。

### 2.4 默认测试工具假设错误

模型尝试运行 `pytest`，环境中并未安装：

```text
/bin/bash: pytest: command not found
/usr/bin/python3: No module named pytest
```

检查 `run.sh` 后确认项目使用自定义测试 runner，改为 `./run.sh test`，最终得到 55/55。

这说明模型熟悉常见 Python 工程习惯，但“常见”不等于“本项目实际”。项目入口脚本和 README 应优先于默认工具链假设。

### 2.5 异步工具状态增加了操作复杂度

长测试和矩阵命令经历了两层异步状态：第一次返回 cell ID，继续等待后又返回底层 session ID，需要再用 stdin polling。模型能够继续推进，但产生了多次空轮询。

这不是代码能力问题，却会影响长任务可靠性：如果模型把“工具调用完成”和“底层进程完成”混淆，可能过早报告测试成功或启动冲突命令。因此最终结论必须依据进程退出和完整输出，而不是依据一次 wait 返回。

### 2.6 外部网络状态不稳定

v4 阶段推送 GitHub 时：

- SSH 22 端口连接被关闭；
- GitHub SSH 443 入口也被关闭；
- 本地 v4 封存有效，但远端未同步。

v5 完成后，同一远端推送成功：

```text
main -> main
[new tag] paper-artifact-v5 -> paper-artifact-v5
```

这说明外部基础设施失败不应直接归因于代码或模型，也不能通过重复改代码解决。模型需要区分“本地目标已完成”和“外部状态尚未同步”，并保留可重试的本地提交与标签。

### 2.7 GPIO blocker 比表面现象更简单

`gpio-idt3243x` 的生成代码包含：

```text
REHARNESS_UNSUPPORTED callback: gpio_chip.init_hw=idt_gpio_irq_init_hw
```

表面上像是缺少 source-private state；实际根因是 callback 分类的优先级错误：`init_hw` 的函数参数是 `struct gpio_chip *`，模型/代码因此把它归到 `gpio_chip`，但赋值目标 `girq->init_hw` 属于 `gpio_irq_chip`。

修复不是增加 neutral stub，而是让字段语义优先于宽泛参数类型，并增加动态赋值回归测试。这是模型在有源码、生成物和 callback parser 三方证据时较擅长的局部根因定位。

### 2.8 Clock blocker 比最初计划更复杂

`clk-highbank` 最初只显示“non-MMIO clock arithmetic unsupported”，但深入检查后发现至少四层问题：

1. MMIO-only RIS 丢失了读取寄存器后的纯标量计算和 return 表达式；
2. `FactsSpec.callbacks` 的 `table.field -> function` 映射对多个 `clk_ops.recalc_rate` 是 last-field-wins；
3. `determine_rate` 没有 MMIO，因此不会进入原有 RIS module；
4. `clk_get` 资源检测使用子串匹配，把 `of_clk_get_parent_name` 误判成 consumer clock acquisition。

最终实现采用保守的 source-backed lowering：只在能明确重绑定 source-private clock container、没有残余未绑定成员、纯 helper 可提取且真实 Kbuild 通过时，保留原始标量语义和多个 callback table；否则仍回退到 unsupported marker。

这里也暴露了模型的一个边界：它可以在具体样本上构造可验证的保守 lowering，但这不等于已经发明了适用于任意 C 控制流的通用标量 IR。

## 3. 大模型在本次过程中的实际表现

### 3.1 表现较好的方面

#### 跨层证据关联

模型能把以下证据关联起来：

- matrix blocker；
- `.facts/.dspec/.ris`；
- 生成的 Linux C；
- callback parser 和 generator 代码；
- Kbuild 编译结果；
- QEMU oracle；
- 论文生成宏。

这种能力适合“症状不在根因所在层”的工程任务。例如 GPIO 的错误出现在生成器输出，根因却在 callback inference；clock 的错误看似是 arithmetic，实际还涉及 callback instance、resource inference 和 readiness gate。

#### 能在失败后修正假设

本次出现了错误仓库根、错误 JSON schema、错误测试入口、缺失宏常量等情况。模型没有在第一次失败后停住，而是继续检查结构、编译日志和项目脚本，逐步收敛。

#### 愿意保持负面结论

模型没有把 original Kbuild 的 warning retry 写成 strict modpost success，也没有通过删除 `REHARNESS_UNSUPPORTED` 或放宽所有 readiness 条件来美化结果。Clock 的 fixed MMIO 被允许参与“存在寄存器访问”的判定，但 unsafe computed、Top、编译失败和 unsupported marker 仍保持 blocker。

#### 长任务制品管理

模型完成了实现提交、重新生成 JSON、重跑 QEMU、构建论文、冻结提交、annotated tag、推送和最终 clean-tree 审计。这说明在有明确检查表和机器验证时，模型可以承担较长的仓库维护链路。

### 3.2 出现的模型问题

#### 过早模式补全

错误 JSON schema 和默认使用 pytest 都来自“按常见工程模式补全未知信息”。这种行为在写草案时高效，在实验审计和基础设施操作中则会制造假设错误。

#### 局部完成容易掩盖全局漂移

模型在 v4 时修正了 REPRO 数字，但 README、PROMPT 和论文中的旧叙述直到 v5 后续审计才被发现。说明模型天然倾向于围绕当前 blocker 缩小注意范围；如果没有全文搜索和 completion audit，容易留下跨文档不一致。

#### 具体样本解法可能被误认为通用能力

Clock source lowering 对 `clk-highbank` 有效，并采用保守拒绝策略，但它仍依赖可识别的 C 语法形状：

- `struct private *x = converter(hw)`；
- 私有 MMIO 字段为 `x->reg`；
- callback table 是静态 `struct clk_ops` initializer；
- helper 无未绑定 aggregate member；
- `CLK_OF_DECLARE` 形式可解析。

如果仅看 readiness 从 4/19 到 6/19，容易误判为“模型已解决通用 clock semantics”。实际上，模型解决的是一个有清晰保守边界的 source-to-source lowering 子域。

#### 代码复杂度控制依赖人工/测试约束

核心 generator 改动约 281 行。模型能够让它通过现有测试和 Kbuild，但没有独立的架构评审者来判断长期可维护性，也没有证明这比扩展 FormalRIS 标量语义更优。大模型容易选择“当前仓库中最快可验证的完整路径”，不天然保证长期架构最简。

#### 验证器决定了模型能看见的正确性

`clk-highbank` 的证据包括源码语义保留断言和真实 Kbuild，但没有对应硬件/QEMU 的 rate 行为 oracle。因此“Linux strict-ready”表示满足 reharness 当前定义的 gate，不表示已经证明与真实 Highbank 硬件完全等价。

模型无法凭代码外观补足缺失的实验。没有 oracle 的语义维度，只能标为未证明，而不能由模型自信程度代替。

## 4. 能力边界分级

| 工作类型 | 本次实测能力 | 必要条件 | 边界 |
|---|---|---|---|
| 仓库搜索、定位、局部修改 | 较强 | 可读取完整源码和生成物 | 会受错误路径、陈旧摘要影响 |
| 跨文件根因分析 | 较强 | blocker、源码、IR、生成代码可同时检查 | 缺任一层证据时容易按模式猜测 |
| Linux API/类型正确性 | 中等 | 必须以固定内核真实 Kbuild 验证 | 不能依赖模型记忆判断版本 API |
| 运行时因果分析 | 中等 | 需要完整 QEMU/serial/oracle 输出 | 空输出、未观测硬件行为无法可靠推断 |
| callback/状态模式推广 | 中等 | 语法形状明确、保守拒绝、回归测试 | 具体 lowering 不等于任意 C 语义建模 |
| 语义等价证明 | 弱 | 需要形式证明或覆盖目标行为的 oracle | 编译、无 marker、代码相似都不是证明 |
| 长周期任务管理 | 中等偏强 | 明确 plan、频繁状态检查、最终逐项审计 | 容易遗漏不在当前 blocker 附近的文档/制品 |
| Git 封存与复现维护 | 较强 | dirty state、tag、JSON commit 全部核验 | 外部网络/权限仍不可控 |
| 外部端点和基础设施控制 | 弱 | 只能重试、切换入口或报告 | 不能保证网络、SSH、LLM endpoint 可用性 |

## 5. 本次结果不能证明什么

必须明确以下负面结论：

1. **6/19 strict-ready 不是 6 个驱动的完整硬件等价证明。** 它是当前 readiness gate、Kbuild 和已有 trace oracle 下的结果。
2. **`clk-highbank` 没有真实 Highbank 硬件或等价 QEMU 运行验证。** 当前最强证据是保留源码算术、table/provider 结构和固定内核编译。
3. **source-backed clock lowering 不是通用 C 标量分析。** 未覆盖任意别名、宏生成 table、复杂 aggregate、函数指针 helper、异常控制流等情况。
4. **本次没有解决 AHCI/SDHCI/virtio/USB 的完整 lifecycle。** DWC2 仍有 199 个 unsafe dynamic address、85 个 clang error diagnostic 和未绑定 callback/lifecycle blocker。
5. **模型成功完成一次长任务，不代表无监督重复运行必然得到同样架构。** 稳定性来自版本化源码、测试、JSON、QEMU、Git tag 和显式审计，而不是模型输出本身可重复。

## 6. 对后续大模型评估的建议

### 6.1 将评估拆成三层

1. **编辑正确性**：补丁是否局部合理、测试是否通过。
2. **系统正确性**：矩阵、Kbuild、QEMU、论文数据是否一致。
3. **认知正确性**：模型是否明确哪些结论已证明、哪些只是推测或当前 gate 的定义。

只统计“任务完成率”会混淆这三层。

### 6.2 强制 schema-first 和 repo-root-first

每次接续任务先执行：

- 确认真实 Git root、HEAD、dirty state、submodule；
- 枚举 JSON keys/schema；
- 读取项目自己的 test/build 入口；
- 再采用上一模型摘要。

这能减少本次最典型的过早假设错误。

### 6.3 为每个 readiness 提升建立反作弊证据

至少要求：

- blocker 消失的具体原因；
- 生成代码中没有 neutral stub 冒充；
- 真实目标编译；
- 关键语义的正向和反向 oracle；
- readiness 规则未被针对单例无原则放宽。

对 `clk-highbank`，下一步应补一个可独立执行的 rate arithmetic reference test，比较原始公式与生成 callback 在代表性寄存器值和 parent rate 上的输出。

### 6.4 把工程代理行为本身结构化记录

建议后续保存机器可读的 agent run manifest：

- 起始/结束 commit；
- 执行过的命令和退出码；
- 失败分类（代码、环境、网络、模型假设）；
- 修改文件；
- 最终证据；
- 未验证声明。

这样可以评估模型的自修能力、无效尝试比例和证据质量，而不只依赖对话回忆。

### 6.5 保持确定性系统主导

本次与早期驱动合成实验得到相同结论：大模型最适合提出候选解释和补丁，最终可信度必须来自确定性系统：

- libclang/IR；
- 编译器和固定内核；
- QEMU/硬件 oracle；
- schema 化结果；
- Git 冻结版本。

## 7. 结论

本次实测说明，大模型作为工程代理能够完成跨 extractor、spec inference、generator、verification、paper 和 Git 的长链路任务，也能在多次假设失败后依靠工具反馈收敛。它最有价值的能力是跨层关联和快速构造可验证候选。

其边界同样清楚：模型会过早套用常见模式，会遗漏远离当前 blocker 的一致性问题，会把具体样本的可行 lowering 推向“看似通用”的实现，并且无法在没有 oracle 时证明语义正确。可靠工程流程不能以“模型认为完成”为终点，而必须以逐项、可机器复核的 completion audit 为终点。
