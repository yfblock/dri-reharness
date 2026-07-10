# Reharness 项目续写提示词

> 将以下内容完整粘贴给 AI（Claude/ChatGPT/DeepSeek），附上 `README.md`、`plan.md`、`recom.md` 作为参考文件。AI 读完后即可接手项目。

---

## 角色

你是一名操作系统内核与程序分析领域的高级工程师。我正在开发一个叫 **reharness** 的工具，用于从 Linux C 设备驱动中提取寄存器交互序列（RIS），并生成后端无关的形式化规约，最终驱动多后端代码生成和 LLM 辅助合成。

**你的任务是帮我完成 reharness 项目的剩余工作，使系统达到论文投稿水平。**

## 项目背景

reharness 是一篇 ACM 顶会论文的核心系统。论文标题：
> *reharness: AST-Driven Extraction of Formal Register Interaction Specifications from C Device Drivers*

**三大贡献：**
1. RIS 形式化规约语言（.ris）—— 描述驱动对寄存器的 Read/Write/RMW/Cond/Loop/Delay 操作序列
2. libclang AST + 流敏感数据流/污点追踪的提取流水线 —— 解决正则方案的四个硬伤
3. 后端无关的语义推断（FunctionSpec → DeviceSpec）+ 多后端代码生成 + 闭环 LLM 辅助合成

**目标读者：** 熟悉操作系统、程序分析、形式化方法的审稿人。系统必须在技术上站得住脚。

## 当前代码状态（已完成）

### extractor/（提取器，~3500 行）
| 模块 | 行数 | 状态 | 说明 |
|------|------|------|------|
| `tu.py` | 83 | ✅ 完成 | libclang TU 解析，容错模式 |
| `macros.py` | 144 | ✅ 完成 | 宏偏移表，preprocessing records |
| `ast_model.py` | 240 | ✅ 完成 | Func/CallSite 数据模型 |
| `mmio.py` | 104 | ✅ 完成 | MMIO 调用识别（readl/writel/ioremap 等） |
| `taint.py` | 118 | ✅ 完成 | 抽象值域：BasePtr/Offset/ReadTaint/Const/SymExpr/Top |
| `dataflow.py` | 484 | ✅ 完成 | 流敏感数据流分析，RMW 检测 |
| `call_graph.py` | 70 | ✅ 完成 | 过程间调用图内联（深度≤3） |
| `intent.py` | 68 | ✅ 完成 | 意图标注（Interrupt/Clock/Config/Status） |
| `formal.py` | 289 | ✅ 完成 | RIS 形式化 IR（Expr/RISOp/FormalRIS） |
| `formalize.py` | 135 | ✅ 完成 | .ris 文本输出 |
| `spec.py` | 479 | ✅ 完成 | FunctionSpec/DeviceSpec/BindSpec 数据模型 |
| `spec_infer.py` | 518 | ✅ 完成 | 语义推断：角色/签名/绑定/效果/前后条件 |
| `metrics.py` | 236 | ✅ 完成 | 提取质量评分 + generation readiness |
| `alias.py` | 160 | ⚠️ 原型 | SVF 别名分析，需要集成到主流水线 |
| `cli.py` | 311 | ✅ 完成 | CLI 入口（extract/show/compare/demo/test） |
| `extractor.py` | 101 | ✅ 完成 | 主提取流水线 |

### generator/（代码生成，~445 行）
| 模块 | 行数 | 状态 | 说明 |
|------|------|------|------|
| `common.py` | 140 | ✅ 完成 | 共享 codegen IR lowering |
| `harness.py` | 134 | ✅ 完成 | Userspace harness 后端（fake MMIO + trace） |
| `baremetal.py` | 64 | ⚠️ 最小 | Bare-metal C 后端骨架 |
| `linux.py` | 97 | ⚠️ 骨架 | Linux 内核驱动骨架 |

### synthesis.py（LLM 合成，289 行）
| 状态 | 说明 |
|------|------|
| ⚠️ 框架搭好 | bundle assembly + verify loop 骨架，LLM 客户端为 no-op stub |

### 已验证的驱动提取结果
- `gpio-ftgpio010`: 22 ops, 100% symbolic, 8 RMW, 1 cond, 9 regs ✅
- `virtio_mmio`: 21 ops, 100% symbolic, 2 RMW, 0 conds, 16 regs ✅
- `gpio-pl061`, `gpio-cadence`: 部分数据 ✅
- **总计 17 驱动**: 461 ops / 129 寄存器解析 / 77 RMW / 62 分支条件 / 100 寄存器映射项 ✅

### 已通过的验证
- harness 生成 + 编译 + trace 输出 ✅（gpio-ftgpio010, virtio_mmio）
- bare-metal 编译 ✅（`cc -ffreestanding -c`）
- `./run.sh test` 测试套件 ✅
- CodeQL 对比实验：reharness 100% vs CodeQL 65% 检出率 ✅

## 待完成任务（按优先级排序）

### P0：必须在 8 月 4 日前完成（论文实验数据支撑）

#### 1. SVF 别名分析集成（alias.py → 主流水线）

当前 `alias.py` 是独立原型，需要：
- [ ] 将 SVF 别名分析结果集成到 `dataflow.py` 的抽象值域中
- [ ] 当 SVF 发现额外的 MMIO base 别名时，自动注入 dataflow 的 taint source
- [ ] 添加 CLI flag `--svf` 启用 SVF 增强模式
- [ ] 对 `gpio-ftgpio010` 和 `virtio_mmio` 运行 SVF 增强提取，对比结果
- [ ] 写测试验证 SVF 别名注入不会破坏现有提取结果

**注意：** SVF 需要 LLVM 16+。本机 SVF 路径：`~/SVF/Release-build/bin/svf-mmio-alias`，libclang 路径：`/usr/lib/llvm-18/lib/libclang-18.so.18`

#### 2. 完善 .dspec/.bind/.facts 输出（formalize.py + spec.py）

当前 `formalize.py` 只输出 .ris 文本。需要扩展为四层规约输出：
- [ ] `.ris` — 已完成 ✅
- [ ] `.dspec` — 从 FunctionSpec + DeviceSpec 生成后端无关的设备语义规约
- [ ] `.bind` — 生成 Linux/bare-metal/harness 三个后端的绑定文件（合并到一个文件，三个 backend block）
- [ ] `.facts` — 提取源码事实（includes, structs, constants, callbacks, resources, error paths）
- [ ] 输出到 `output/<driver>/` 目录，结构对齐 recom.md 的推荐布局
- [ ] CLI 新增 `formalize` 子命令：`./run.sh formalize <driver>`

#### 3. 17 驱动完整提取 + 实验数据收集

- [ ] 对 17 个驱动运行完整提取，生成 .ris + .dspec + .bind + .facts
- [ ] 收集提取时间数据（libclang 解析时间 vs 正则提取时间）
- [ ] 生成完整的 `compare.py` 报告（当前只有部分数据）
- [ ] 将实验数据整理为论文 §8 Evaluation 需要的格式

#### 4. virtio 端到端验证

- [ ] 完整流程：提取 virtio_mmio → 生成 harness → 编译 → 执行 → trace 对比
- [ ] 验证生成的 harness trace 与 .ris 规约中的操作序列一致
- [ ] 记录端到端验证结果（成功/失败 + 具体 trace diff）

### P1：8 月 5 日 - 8 月 18 日（论文撰写支撑）

#### 5. LLM 语义补全管线完善（synthesis.py）

当前 synthesis.py 是 no-op stub。需要：
- [ ] 实现真实的 LLM 客户端（通过 `REHARNESS_LLM_CMD` 环境变量调用外部 LLM）
- [ ] 完善 bundle assembly：为每个驱动生成完整的 `(RIS, dspec, bind, facts, scaffold, constraints, verification)` 输入包
- [ ] 完善 verify loop：编译检查 + 静态检查 + trace 对比 → 结构化反馈
- [ ] 实现 repair prompt 格式化：将验证失败信息转为 LLM 可理解的修复指令
- [ ] 用 3 个驱动（gpio-ftgpio010, virtio_mmio, gpio-cadence）跑 LLM 修复实验
- [ ] 收集修复轮次、收敛率、最终代码质量数据

#### 6. bare-metal 后端完善

- [ ] 生成完整的 bare-metal C 代码（不只是骨架）
- [ ] 包含：设备状态结构体、寄存器常量、read32/write32 包装、RIS-backed 函数体
- [ ] 编译验证：`cc -ffreestanding -c -Wall -Werror`
- [ ] 对 gpio-ftgpio010 和 virtio_mmio 生成并验证

#### 7. Linux 后端完善

- [ ] 生成 Linux 平台驱动骨架：`struct device_state`, `probe/remove`, `of_device_id`, ops table
- [ ] RIS-backed callback 函数体
- [ ] 不支持的语义生成明确的 TODO 注释（不要静默错误）
- [ ] 对 gpio-ftgpio010 生成并验证

#### 8. QEMU 端到端验证（可选但加分）

- [ ] 搭建 QEMU 环境（virtio-blk + virtio-net）
- [ ] mmiotrace 轨迹录制脚本
- [ ] 偏序对齐算法：将生成的 harness trace 与真实 mmiotrace 对齐
- [ ] 验证提取的 RIS 与真实硬件行为一致

### P2：持续改进

#### 9. 测试完善

- [ ] 为 spec_infer.py 添加角色推断测试
- [ ] 为 generator/ 添加 trace 等价性测试
- [ ] 为 synthesis.py 添加 bundle assembly 测试
- [ ] 确保 `./run.sh test` 全部通过

#### 10. 代码质量

- [ ] 确保所有新代码有 docstring
- [ ] 类型注解完整
- [ ] 错误处理健壮（libclang 解析失败、文件不存在等）

## 代码规范

- **语言：** Python 3，无额外依赖（只用 clang.cindex + 标准库）
- **风格：** 跟现有代码保持一致（看 extractor/*.py 的风格）
- **测试：** 放在 `tests/` 目录，兼容 pytest 也能独立运行
- **输出格式：** .ris/.dspec/.bind/.facts 是唯一正规输出，不产 JSON
- **libclang 路径：** `/usr/lib/llvm-18/lib/libclang-18.so.18`
- **SVF 路径：** `~/SVF/Release-build/bin/svf-mmio-alias`（需要 LLVM 16）
- **驱动源码：** `drivers/` 目录（symlink 到 `../driver-harness/drivers`）
- **Linux 源码：** `linux/` 目录（symlink 到 `../driver-harness/linux`）

## 工作方式

1. **先读代码：** 读 `README.md`、`plan.md`、`recom.md` 和 `extractor/` 下的关键模块（spec.py、spec_infer.py、dataflow.py、formalize.py）
2. **跑现有测试：** `./run.sh test` 确认基线正常
3. **跑提取：** `./run.sh demo` 看当前输出
4. **按优先级逐个完成任务：** P0 → P1 → P2
5. **每完成一个任务：** 跑测试验证，更新 `./run.sh compare` 统计
6. **提交粒度：** 每个独立功能一个 git commit，message 说明做了什么

## 关键约束

- **不要破坏现有功能：** 任何改动都要保证 `./run.sh test` 和 `./run.sh demo` 通过
- **不要引入外部依赖：** 除了 clang.cindex 和标准库，不加新的 pip 包
- **不要虚构数据：** 实验数据必须来自真实运行，宁可 TBD 也不要编造
- **形式化规约必须可解析：** .ris/.dspec/.bind/.facts 必须是格式正确的文本，能被对应的 parser 解析
- **代码生成必须可编译：** 生成的 harness.c 必须 `cc -Wall` 通过，baremetal.c 必须 `cc -ffreestanding -c` 通过

## 参考文件

请阅读以下文件获取完整上下文：
1. `README.md` — 项目说明和提取统计
2. `plan.md` — 完整技术方案、里程碑、形式化定义
3. `recom.md` — 输出规范化建议
4. `paper/paper.tex` — 当前论文全文（了解论文视角下的系统描述）
5. `extractor/spec.py` — 形式化规约数据模型
6. `extractor/spec_infer.py` — 语义推断实现
7. `extractor/dataflow.py` — 数据流分析核心
8. `synthesis.py` — LLM 合成框架

## 起始指令

请先：
1. 阅读上述参考文件
2. 运行 `./run.sh test` 和 `./run.sh demo` 确认当前状态
3. 给出你对项目的理解和接下来的工作计划
4. 然后从 P0 的第一个任务开始
