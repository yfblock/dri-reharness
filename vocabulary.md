# 生词本 (Vocabulary Notebook)

> 记录我不熟悉的单词、释义及文章中出现的原句，便于学习和复习。
>
> - 格式：`单词 | 词性 | 释义` + 原文例句
> - 复习建议：遮住释义，根据句子回忆单词意思；或用例句自测造句

---

## 生词记录

## mediate
- **释义**：v. 调解、斡旋；传达、传递（经中介物起作用）；adj.（学术/技术语境）间接的、居间的
  - 常见搭配：mediate between A and B（在两者之间调解）；mediated by（由…中介/介导）
- **原文句子**：Device drivers **mediate** nearly every interaction between an operating system and its peripherals, yet porting a driver from one target to another---from Linux to a bare-metal firmware, a hypervisor back-end, or a memory-safe language---remains a manual, error-prone effort repeated for every new environment.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：设备驱动程序在操作系统与其外设之间的几乎所有交互中起着中介作用，然而将一个驱动从一个目标移植到另一个目标——从 Linux 到裸机固件、到 hypervisor 后端、或到内存安全语言——仍然是一项对每个新环境都要重复的、手动且易错的工作。*

## remain（remains）
- **释义**：v. 仍然是、依然保持（系动词，类似 be 但强调“状态始终未变”）
  - 结构：remain + 名词/形容词
- **原文句子**：...remains a manual, error-prone effort repeated for every new environment.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…仍然是一项对每个新环境都要重复的、手动且易错的工作。*
  - *为何用 remains：强调“尽管环境在变，这项工作的性质始终未变”，比 is 多了“持续未变”的语气*

## error-prone
- **释义**：adj. 容易出错的、易产生错误的（构词：error 错误 + -prone 易于…的；-prone 常接消极概念：accident-prone 易出事故的 / injury-prone 易受伤的 / flood-prone 易发洪水的）
- **原文句子**：...remains a manual, **error-prone** effort repeated for every new environment.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…仍然是一项对每个新环境都要重复的、手动且容易出错的工作。*

## preprocessor
- **释义**：n. 预处理器（编译前先处理源码的阶段；处理 #include / #define / #ifdef 等指令；构词：pre- 预先 + processor 处理器）
  - 相关：preprocess v. 预处理；macro 宏（#define 定义）
- **原文句子**：The root cause is that a driver's register-level contract is implicit in C source, obscured by **preprocessor macros**, pointer arithmetic, framework idioms, and header-inlined accessors.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：根本原因在于驱动的寄存器级契约在 C 源码中是隐含的，被预处理器宏、指针运算、框架惯用法以及头文件内联的访问函数所掩盖。*

## arithmetic
- **释义**：n. 算术、运算；adj. 算术的（读音 /əˈrɪθmətɪk/，重音在 thm 前）
  - 计算机语境：pointer arithmetic = 指针运算（直接对地址做加减，如 base + 0x20）
- **原文句子**：The root cause is that a driver's register-level contract is implicit in C source, obscured by preprocessor macros, **pointer arithmetic**, framework idioms, and header-inlined accessors.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：根本原因在于驱动的寄存器级契约在 C 源码中是隐含的，被预处理器宏、指针运算、框架惯用法和头文件内联访问函数所掩盖。*

## idiom
- **释义**：n. 习语、惯用语；（技术语境）惯用法、约定俗成的典型写法
  - 语言学：习语（kick the bucket 去世）；编程语境：framework idioms = 框架惯用法（Linux 驱动里 writel/readl、devm_ioremap 等固定写法模式）
- **原文句子**：The root cause is that a driver's register-level contract is implicit in C source, obscured by preprocessor macros, pointer arithmetic, **framework idioms**, and header-inlined accessors.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：根本原因在于驱动的寄存器级契约在 C 源码中是隐含的，被预处理器宏、指针运算、框架惯用法和头文件内联访问函数所掩盖。*
  - *另见 sections_1_2.tex：register access idioms 寄存器访问惯用法*

## accessor
- **释义**：n. 访问器、访问函数（编程术语；构词：access 访问 + -or 表“…者/…物”）
  - OOP 中指 getter/setter；驱动中指封装寄存器读写的函数（readl/writel、dw_readl 等）
  - header-inlined accessors = 头文件中 static inline 定义的访问函数（编译时内联展开，源码层面看不到实际 MMIO 操作）
- **原文句子**：The root cause is that a driver's register-level contract is implicit in C source, obscured by preprocessor macros, pointer arithmetic, framework idioms, and **header-inlined accessors**.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：根本原因在于驱动的寄存器级契约在 C 源码中是隐含的，被预处理器宏、指针运算、框架惯用法和头文件内联的访问函数所掩盖。*

## innovation
- **释义**：n. 创新、革新；（具体指）新方法、新事物
  - 构词：in- 进入 + nov-（拉丁词根 novus = 新的）+ -ation；同根词：novel 新颖的 / novelty 新奇事物 / novice 新手 / renovate 翻新
- **原文句子**：\reharness introduces four **innovations**: (1)~a hybrid extraction pipeline pairing libclang AST analysis...; (2)~the \rislang{} language...; (3)~a plugin-based multi-backend generator...; and (4)~a verification gate...
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：Reharness 提出四项创新：混合提取流水线、RISA 语言、基于插件的多后端生成器、验证关卡。*

## taint
- **释义**：n. 污点、污染；v. 污染、玷污
  - 普通用法：tainted water 受污染的水；His reputation was tainted. 名声被玷污
  - 静态分析术语：taint tracking = 污点追踪（给特定来源的数据打标签并追踪其流向，用于识别 RMW 等模式）
- **原文句子**：...a hybrid extraction pipeline pairing libclang AST analysis---with flow-sensitive dataflow and **taint tracking**---with LLVM-IR evidence that recovers MMIO operations erased by header inlining...
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…一种混合提取流水线，将 libclang AST 分析（带流敏感数据流分析与污点追踪）与 LLVM-IR 证据相结合，以恢复被头文件内联抹掉的 MMIO 操作。*
  - *另见 sections_3_5.tex：readl 返回值被标记为 ReadTaint，链接回源寄存器地址*

## recover
- **释义**：v.（技术语境）重新获得、找回、恢复被隐藏/丢失的信息；普通义：康复（recover from illness）、追回（recover lost data）
  - 本文中：因 static inline 函数被内联，AST 看不到 MMIO 操作，编译到 LLVM-IR 层把操作“找回来”
  - 名词：recovery 恢复、找回（LLVM-IR evidence recovery）
- **原文句子**：...with LLVM-IR evidence that **recovers** MMIO operations erased by header inlining...
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…与 LLVM-IR 证据相结合，以恢复被头文件内联抹掉的 MMIO 操作。*
  - *另见 sections_1_2.tex：Recovering this contract is the prerequisite for any automated porting.（恢复该契约是任何自动化移植的前提。）*

## capture
- **释义**：v. 捕捉、捕获；（技术/学术语境）捕捉、涵盖、完整表达出（某种信息/语义）
  - 普通用法：capture a photo 拍下照片
  - 技术用法：The language captures the semantics. 该语言完整表达了这种语义。
- **原文句子**：...the \rislang{} language, which **captures** not only raw register reads, writes, and read-modify-write patterns but also typed bus transactions and functional-state operations that preserve buffer-to-register data flow.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…RISA 语言不仅涵盖了原始的寄存器读写和 RMW 模式，还涵盖类型化总线事务及功能状态操作。*
  - *另见 sections_3_5.tex：Functional-state operations capture data flow between software state and device registers.*

## preserve
- **释义**：v. 保护、保存、保留（使…保持原状不丢失）
  - 普通用法：preserve food 保存食物；技术用法：preserve the data flow 保留数据流语义
  - 名词：preservation 保留、保持
- **原文句子**：...typed bus transactions and functional-state operations that **preserve** buffer-to-register data flow.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…类型化总线事务及功能状态操作，这些操作保留了缓冲器到寄存器的数据流。*
  - *另见 sections_1_2.tex：generated drivers that preserve not only the register interaction sequence but also the data-movement semantics（生成的驱动不仅保留寄存器交互序列，还保留数据移动语义）*

## receipt
- **释义**：n. 收据、凭证；（技术语境）可验证的记录/证明
  - 普通用法：receipt of payment 付款凭证
  - 本文用法：AST lowering receipt = AST 降低凭证（每条 RISA 操作生成一条记录，记录其 ID、摘要和生成形式，用于验证所有操作都被正确生成、无重复、类型匹配）
- **原文句子**：...a verification gate that independently checks compilation, **AST lowering receipts**, and trace oracles before accepting any candidate.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…一个验证关卡，在接受任何候选项之前，独立检查编译、AST 降低凭证和追踪预言机。*
  - *另见 sections_6_8.tex：The receipt reconciliation enforces four properties.（receipt 对账机制强制执行四个属性。）*

## deterministic
- **释义**：adj. 确定性的（给定相同输入结果完全可预测、可复现；与 random 相对）
  - 构词：determine（决定）+ -istic；名词：determinism 决定论
  - 本文用法：deterministic-emitter = 确定性发射器（LLM 输出可复现的基线）
- **原文句子**：...with **deterministic** QEMU trace validation passing on two real devices.
  - *出处：research/paper/v2/main.tex（摘要）*
  - *句意：…确定性的 QEMU 追踪验证在两个真实设备上通过。*
  - *另见 sections_6_8.tex：keeping all verification checks deterministic（确保所有验证检查都是确定性的）*

## constitute
- **释义**：v. 构成、组成；是（等于）
  - 搭配：constitute the majority of 构成…的大部分；constitute a threat/crime 构成威胁/犯罪
  - 方向：A constitute B = 部分 A 构成整体 B（注意：不是“B 包含 A”）
- **原文句子 1**：Device drivers **constitute** the majority of operating system kernel code and account for a disproportionate share of kernel faults.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction 开头）*
  - *句意：设备驱动程序构成了操作系统内核代码的大部分，并且在内核故障中占了不成比例的份额。*
- **原文句子 2**：...not the *conditional* structure---guarded then/else branches, loops, delays---that **constitutes** the driver's full protocol.
  - *出处：research/paper/v2/sections_1_2.tex（符号执行部分）*
  - *句意：…而不是构成驱动完整协议的条件结构（受保护的分支、循环、延迟等）。*

## disproportionate
- **释义**：adj. 不成比例的、过大的（超出合理/预期范围）
  - 构词：dis- 否定 + proportionate 成比例的（proportion 比例）
  - 含义：故障占比远超代码占比，暗示驱动是最容易出 bug 的部分
- **原文句子**：Device drivers constitute the majority of operating system kernel code and account for a **disproportionate** share of kernel faults.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction 开头）*
  - *句意：设备驱动程序构成了操作系统内核代码的大部分，并且在内核故障中占了不成比例的份额。*

## tens of thousands
- **释义**：成千上万（数以万计；tens of 几十个 × thousands 千 = 几万）
  - 类似表达：hundreds of 几百 / thousands of 几千 / tens of thousands 成千上万 / hundreds of thousands 几十万 / millions of 几百万
- **原文句子**：A modern Linux release ships **tens of thousands** of driver source files, each encoding a precise hardware protocol through memory-mapped I/O (MMIO) accesses, interrupt handlers, and framework callbacks.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：一个现代 Linux 发行版包含成千上万个驱动源文件，每个文件通过 MMIO 访问、中断处理程序和框架回调来编码精确的硬件协议。*

## subtle
- **释义**：adj. 微妙的、细微的（难以察觉但确实存在的）
  - 发音注意：b 不发音，读作 /ˈsʌtl/
  - 常见搭配：subtle difference 微小差别；subtle hint 暗示；subtle bug 难发现的 bug
- **原文句子**：This manual porting is expensive, introduces **subtle** semantic divergences, and must be repeated for every target.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：这种手动移植代价高昂，会引入微妙的语义偏差，并且必须为每个目标重复进行。*

## semantic
- **释义**：adj. 语义的（关于含义而非形式；构词：sema 符号/意义 → semantics 语义学）
  - 核心对立：syntax 语法/形式 vs semantics 语义/含义
  - 本文高频词：semantic divergences 语义偏差；semantic contract 语义契约；semantic checks 语义检查；data-movement semantics 数据移动语义
- **原文句子 1**：This manual porting is expensive, introduces subtle **semantic** divergences, and must be repeated for every target.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：这种手动移植代价高昂，会引入微妙的语义偏差，并且必须为每个目标重复进行。*
- **原文句子 2**：Framework translation moves the syntax without recovering the **semantic** contract.
  - *出处：research/paper/v2/sections_1_2.tex（框架翻译部分）*
  - *句意：框架翻译只搬了语法，却没恢复语义契约。*

## divergence
- **释义**：n. 分歧、差异、偏差（从同一原点走向不同方向）
  - 构词：di- 分开 + verge 趋向 + -ence；反义：convergence 汇合
  - 词族：diverge v. 分叉 / divergent adj. 有分歧的 / converge v. 汇合
- **原文句子**：This manual porting is expensive, introduces subtle semantic **divergences**, and must be repeated for every target.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：这种手动移植代价高昂，会引入微妙的语义偏差，并且必须为每个目标重复进行。*

## obstacle
- **释义**：n. 障碍、阻碍（阻止前进或达成目标的事物）
  - 搭配：obstacle to success 成功的障碍；overcome an obstacle 克服障碍
  - 词族：obstruct v. 阻塞；obstruction n. 妨碍；obstructive adj. 妨碍的
- **原文句子**：The fundamental **obstacle** is that a driver's register interaction contract---which registers it touches, in what order, under what conditions, and how data flows between software buffers and device state---is never stated explicitly.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：根本障碍在于，驱动的寄存器交互契约从未被显式地陈述出来。*

## contract
- **释义**：n. 合同、契约；（技术语境）契约、规范（规定组件必须遵守的行为规则）
  - 本文多种搭配：register interaction contract 寄存器交互契约；semantic contract 语义契约；evidence contract 证据契约；verification contract 验证契约
  - 类比：数学中的“前置条件/后置条件”（precondition/postcondition）
- **原文句子 1**：The fundamental obstacle is that a driver's **register interaction contract**---which registers it touches, in what order, under what conditions, and how data flows between software buffers and device state---is never stated explicitly.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：根本障碍在于驱动的寄存器交互契约从未被显式陈述出来。*
- **原文句子 2**：Framework translation moves the syntax without recovering the **semantic contract**.
  - *出处：research/paper/v2/sections_1_2.tex（框架翻译部分）*
  - *句意：框架翻译只搬了语法，却没恢复语义契约。*

## explicitly
- **释义**：adv. 明确地、显式地（直接清楚地说明，不含糊）
  - 反义：implicitly adv. 隐式地、含蓄地
  - 核心对立：explicit 显式的 vs implicit 隐式的（计算机科学核心概念）
  - 本文核心观点：驱动契约在源码中是 implicit（隐含的），从未被 explicitly stated（显式陈述），Reharness 要把它提取为 explicit 的形式化规范
- **原文句子**：The fundamental obstacle is that a driver's register interaction contract ... is never stated **explicitly**.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：根本障碍在于驱动的寄存器交互契约从未被显式地陈述出来。*

## bury (buried)
- **释义**：v. 埋葬、掩埋；（抽象）隐藏、埋藏（使难以被发现）
  - 普通：bury the dead 埋葬死者
  - 本文比喻：契约被层层代码“埋藏”，不直接可见
  - 词形：buried adj. 被埋藏的；burial n. 葬礼
- **原文句子**：It is **buried** in C source, tangled with preprocessor macros, pointer arithmetic, framework boilerplate, and header-inlined accessor functions.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：它被埋藏在 C 源码中，与预处理器宏、指针运算、框架样板代码和头文件内联访问函数纠缠在一起。*

## tangle (tangled)
- **释义**：v. 纠缠、缠绕（像线团一样乱成一团）；n. 纠缠、混乱
  - 普通：tangled hair 打结的头发
  - 本文比喻：契约与宏、指针运算等代码特性纠缠在一起，像一团乱麻
  - 反义：untangle v. 解开、理清
- **原文句子**：It is buried in C source, **tangled with** preprocessor macros, pointer arithmetic, framework boilerplate, and header-inlined accessor functions.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：它被埋藏在 C 源码中，与预处理器宏、指针运算、框架样板代码和头文件内联访问函数纠缠在一起。*

## boilerplate
- **释义**：n. 样板文件、模板代码（框架中固定格式、重复出现、不需要动脑的代码）
  - 词源：印刷业——常用段落刻在钢板上直接复制，引申到编程中指“复制粘贴的固定代码”
  - 搭配：framework boilerplate 框架样板代码；driver boilerplate 驱动样板代码
- **原文句子**：It is buried in C source, tangled with preprocessor macros, pointer arithmetic, framework **boilerplate**, and header-inlined accessor functions.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：它被埋藏在 C 源码中，与预处理器宏、指针运算、框架样板代码和头文件内联访问函数纠缠在一起。*

## prerequisite
- **释义**：n. 先决条件、前提（必须先满足才能继续的条件）
  - 构词：pre- 在…之前 + requisite 必需品/必要条件
  - 搭配：prerequisite for … 的前提
- **原文句子**：Recovering this contract is the **prerequisite** for any automated porting, verification, or translation effort.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：恢复这个契约是任何自动化移植、验证或翻译工作的前提。*

## suite
- **释义**：n. 套间、套房（酒店）；（技术语境）套件、成套的工具/测试集
  - 发音：/swiːt/，与 sweet（甜的）同音
  - 常见搭配：evaluation suite 评测套件；benchmark suite 基准测试套件；test suite 测试套件
- **原文句子 1**：In our evaluation **suite**, these four failure modes cause every macro-defined offset and every wrapped accessor to be lost.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：在我们的评测套件中，这四种失败模式导致每个宏定义的偏移量和被包装的访问器都丢失了。*
- **原文句子 2**：Each failure pattern is drawn from real Linux drivers in our evaluation **suite**, and each directly motivates a component of the \reharness{} design.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：每种失败模式都来自我们评测套件中的真实 Linux 驱动，每种都直接驱动了 Reharness 的某个设计组件。*

## concrete
- **释义**：adj. 具体的、实际的（与 abstract 抽象的相对）；n. 混凝土
  - 核心对立：concrete 具体的 vs abstract 抽象的
  - 技术语境：concrete address 具体地址（如 0x20）vs symbolic 符号化的（如 GPIO_INT_EN）；concrete evidence 具体证据
- **原文句子 1**：Symbolic-execution frameworks can, in principle, recover **concrete** register addresses by executing the driver against a symbolic device model.
  - *出处：research/paper/v2/sections_1_2.tex（符号执行部分）*
  - *句意：符号执行框架原则上可以通过在符号设备模型上执行驱动来恢复具体的寄存器地址。*
- **原文句子 2**：...symbolic execution recovers *concrete* addresses for a single execution path, not the *conditional* structure.
  - *出处：research/paper/v2/sections_1_2.tex（符号执行部分）*
  - *句意：符号执行恢复的是单条执行路径的具体地址，而不是条件结构。*

## entangle (entangled)
- **释义**：v. 纠缠、使陷入困境（比 tangle 更强调“难以脱身”，被动意味更强）
  - 构词：en- 使… + tangle 缠绕
  - 词族：entangled adj. 纠缠的；entanglement n. 纠缠
- **原文句子**：In practice, driver code is deeply **entangled** with kernel framework state: callback registration tables, locking primitives, DMA subsystem invariants, and interrupt-dispatch infrastructure that do not exist outside a running kernel.
  - *出处：research/paper/v2/sections_1_2.tex（符号执行部分）*
  - *句意：在实践中，驱动代码与内核框架状态深度纠缠——回调注册表、锁原语、DMA 子系统不变量和中断分发基础设施——这些在运行中的内核之外不存在。*

## infrastructure
- **释义**：n. 基础设施、基础结构（支撑系统运行的底层设施）
  - 构词：infra- 在…之下 + structure 结构 = 底层结构
  - 搭配：transportation infrastructure 交通基础设施；IT infrastructure IT 基础设施；interrupt-dispatch infrastructure 中断分发基础设施
- **原文句子**：...driver code is deeply entangled with kernel framework state: callback registration tables, locking primitives, DMA subsystem invariants, and interrupt-dispatch **infrastructure** that do not exist outside a running kernel.
  - *出处：research/paper/v2/sections_1_2.tex（符号执行部分）*
  - *句意：…驱动代码与内核框架状态深度纠缠：回调注册表、锁原语、DMA 子系统不变量和中断分发基础设施——这些在运行中的内核之外不存在。*

## therefore
- **释义**：adv. 因此、所以（表因果关系，比 so 更正式，学术论文首选）
  - 同义词：thus / hence / consequently（正式）；so（口语）
- **原文句子 1**：Porting a driver to a userspace test harness, bare-metal firmware, another operating-system environment, or a memory-safe language is **therefore** a recurring systems problem.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：将驱动移植到用户空间测试框架、裸机固件、另一个操作系统环境或内存安全语言，因此是一个反复出现的系统问题。*
- **原文句子 2**：The central question is **therefore** not whether translation should use rules or an LLM, but *where nondeterminism is allowed*.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：因此，核心问题不在于翻译该用规则还是 LLM，而在于允许非确定性出现在哪里。*

## recurring
- **释义**：adj. 反复出现的、经常发生的
  - 构词：re- 再次 + cur 发生（拉丁语 currere 跑）+ -ing = 再次跑出来 → 反复出现
  - 搭配：recurring theme 反复出现的主题；recurring cost 持续成本；recursive 递归的（同根但含义不同！）
- **原文句子**：Porting a driver to a userspace test harness, bare-metal firmware, another operating-system environment, or a memory-safe language is therefore a **recurring** systems problem.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：将驱动移植到用户空间测试框架、裸机固件、另一个操作系统环境或内存安全语言，因此是一个反复出现的系统问题。*

## homogeneous
- **释义**：adj. 同质的、同类的（由相同成分组成，内部一致）
  - 构词：homo- 相同 + geneous（genos 种类）= 同一类的
  - 反义：heterogeneous adj. 异质的、不同种类的（hetero- 不同）
- **原文句子**：Although this task is commonly described as source-to-source conversion, a driver is not a **homogeneous** program.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：虽然这项任务通常被描述为源到源转换，但驱动不是一个同质的程序。*
  - *含义：驱动混合了 OS 集成代码（平台相关）和设备核心代码（跨平台通用），内部不一致*

## interleave
- **释义**：v. 交织、交错（将两组事物穿插排列，A-B-A-B）
  - 构词：inter- 相互 + leave 放置 = 放在彼此之间
  - 反义：deinterleave v. 解交织
  - 本文：interleaves two concerns = 将两种关注点交织在一起（OS 集成代码与设备核心代码穿插出现）
- **原文句子**：Its C source **interleaves** two concerns: *operating-system integration* ... and the *device core* ...
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：它的 C 源码交织了两种关注点：操作系统集成和设备核心。*

## survive
- **释义**：v. 幸存、存活；（技术语境）保留下来、在转换后仍然存在
  - 普通：survive the accident 在事故中幸存
  - 技术用法：must survive across backends 必须在所有后端中保留下来；all survive in translated form 翻译后全部保留（有时是不好的，如不该保留的内核 API）
- **原文句子 1**：Only the latter defines the hardware-facing behavior that must **survive** across backends, while the former must be re-bound to the target environment.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：只有后者定义了面向硬件的行为，这些行为必须在所有后端中保留下来，而前者必须被重新绑定到目标环境。*
- **原文句子 2**：A Linux driver's `devm_*` resource calls, callback tables, locking idioms, error-unwind paths, intrusive containers, and kernel object lifetimes all **survive** in translated form.
  - *出处：research/paper/v2/sections_1_2.tex（C2Rust 部分）*
  - *句意：Linux 驱动的各种内核 API 在翻译后都保留了下来（这是 C2Rust 的问题）。*

## re-bound (re-bind)
- **释义**：v.（re- 重新 + bind 绑定）重新绑定
  - 词族：bind v. 绑定 → bound adj. 受约束的 / bind 过去式 → rebind v. 重新绑定 → binding n. 绑定
- **原文句子**：Only the latter defines the hardware-facing behavior that must survive across backends, while the former must be **re-bound** to the target environment.
  - *出处：research/paper/v2/sections_1_2.tex（Introduction）*
  - *句意：只有后者定义了面向硬件的行为（必须保留），而前者（OS 集成部分）必须被重新绑定到目标环境。*

## representation
- **释义**：n. 表示、表达方式；（技术语境）表示形式、数据结构
  - 核心术语：IR = Intermediate Representation 中间表示（编译器中源代码和目标代码之间的中间形态；本文 RISA 就是一种 IR）
  - 搭配：intermediate representation 中间表示；pointer-heavy representation 指针密集的表示形式
- **原文句子 1**：The Register Interaction Sequence (\rislang{}) is the central **intermediate representation** of \reharness{}.
  - *出处：research/paper/v2/sections_3_5.tex（RISA 语言介绍）*
  - *句意：RISA 是 Reharness 的核心中间表示。*
- **原文句子 2**：...consequently carry Linux-specific framework code and its pointer-heavy **representation** into the target.
  - *出处：research/paper/v2/sections_1_2.tex（C2Rust 局限性）*
  - *句意：…同时也把 Linux 特定的框架代码及其指针密集的表示形式带入了目标代码。*

## tied
- **释义**：adj. 被绑住的、受限制的、依赖于……的（tie v. 系/绑 的过去分词）
  - 普通：tied to a chair 被绑在椅子上
  - 技术：tied to APIs = 绑定到特定 API，脱离它们就无法运行
- **原文句子**：The translated program remains **tied** to APIs and lifecycles that may not exist outside Linux, while the device protocol remains implicit in syntax.
  - *出处：research/paper/v2/sections_1_2.tex（C2Rust 局限性）*
  - *句意：翻译后的程序仍然受制于可能在 Linux 之外不存在的 API 和生命周期，而设备协议仍然隐含在语法中。*

## lifecycle
- **释义**：n. 生命周期（事物从创建到销毁的完整过程）
  - 构词：life 生命 + cycle 周期
  - 驱动语境：从 probe() 初始化 → 运行 → remove() 清理的完整过程；devres 内存自动释放机制
  - C2Rust 问题：翻译后仍保留 Linux 特定的生命周期管理，裸机/Rust no_std 环境中不存在
- **原文句子**：The translated program remains tied to APIs and **lifecycles** that may not exist outside Linux, while the device protocol remains implicit in syntax.
  - *出处：research/paper/v2/sections_1_2.tex（C2Rust 局限性）*
  - *句意：翻译后的程序仍然受制于可能在 Linux 之外不存在的 API 和生命周期，而设备协议仍然隐含在语法中。*

## opposite
- **释义**：adj. 相反的、对立的；n. 对立面；prep. 在……对面
  - 搭配：the opposite approach 相反的方法；the opposite direction 相反方向
  - 本文对比：C2Rust 保留结构 vs LLM 翻译重构代码 = opposite approaches
- **原文句子**：Direct large-language-model (LLM) translation takes the **opposite** approach: a model can restructure code and emit idiomatic target APIs, but it is also asked to infer which source behavior matters.
  - *出处：research/paper/v2/sections_1_2.tex（LLM 翻译局限性）*
  - *句意：直接用 LLM 翻译采取了相反的方法：模型可以重构代码并生成地道的目标 API，但同时也被要求推断哪些源代码行为是重要的。*

## plausible
- **释义**：adj. 貌似合理的、看似可信的（听起来有道理，但不一定正确）
  - 词源：plausibilis（值得鼓掌的）→ applause（鼓掌）同源
  - 技术含义：LLM 生成的代码 plausible（编译通过、结构完整），但可能有严重语义错误
  - 关键点：plausible 暗示“表面可信但实际可能有错”，这是 LLM 代码的核心风险
- **原文句子**：A **plausible** candidate may add a DMA command, omit an interrupt acknowledgment, alter a register width, or reorder a buffer update while still compiling successfully.
  - *出处：research/paper/v2/sections_1_2.tex（LLM 翻译局限性）*
  - *句意：一个看似合理的候选代码可能会增加 DMA 命令、省略中断确认、改变寄存器宽度或重排缓冲区更新，同时仍能成功编译。*

## candidate
- **释义**：n. 候选人；（技术语境）候选项、待验证的候选代码
  - 普通：job candidate 求职候选人
  - 本文核心用法：LLM 每次输出的代码都是一个 candidate，必须通过编译+AST receipt+trace 验证三关才能被接受；不过关则带着反馈让 LLM 重新生成（repair loop）
- **原文句子 1**：The verification gate treats every **candidate** as untrusted output.
  - *出处：research/paper/v2/sections_6_8.tex（验证关卡）*
  - *句意：验证关卡将每个候选代码视为不可信的输出。*
- **原文句子 2**：A **candidate** that fails to compile is rejected before more expensive checks run.
  - *出处：research/paper/v2/sections_6_8.tex（编译检查）*
  - *句意：编译失败的候选代码在更昂贵的检查运行之前就被拒绝了。*

## reproducible
- **释义**：adj. 可复现的、可重现的（相同条件下能得到相同结果）
  - 构词：re- 再次 + produce 产生 + -able 能够的
  - 核心对立：reproducible 可复现的（C2Rust 确定性翻译）vs nondeterministic 非确定性的（LLM 每次可能不同）
- **原文句子 1**：Deterministic translators such as C2Rust preserve the source program structurally and **reproducibly**.
  - *出处：research/paper/v2/sections_1_2.tex（C2Rust 介绍）*
  - *句意：C2Rust 等确定性翻译器可复现地保留了源程序的结构。*
- **原文句子 2**：A **reproducible** evaluation over \EvalDrivers{} single-source drivers ...
  - *出处：research/paper/v2/sections_1_2.tex（贡献列表）*
  - *句意：对多个单源驱动进行了可复现的评估……*

<!-- 新单词从这里开始追加 -->

