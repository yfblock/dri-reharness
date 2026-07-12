# LLM 在驱动合成中的问题与能力边界（实测记录）

> 基于 reharness 用 opencode(deepseek-v4-flash) 和 Pi SDK(glm-5.2) 合成 Linux 驱动（edu / gpio-ftgpio010）的实测观察。所有案例均有 git 提交 / history / iter_log 可查。

## 一、观察到的问题（按危害排序）

### P1. 无视显式约束（最致命）
- **现象**：合成 prompt 里"probe 禁止 DMA/request_irq"写了 5 遍，glm-5.2 的"修复"反而把 `dma_alloc + writel(DMA_CMD|DMA_IRQ)` 加了回去。
- **后果**：`writel(DMA_CMD|DMA_IRQ, IO_DMA_CMD)` 启动 DMA 并 raise 中断 → QEMU edu 中断风暴 → guest 硬挂 → QEMU 被 timeout 杀 → stdout 缓冲全丢 = **0 字节输出** → 喂回 LLM 的错误为空 → LLM 瞎猜 → 反复加 DMA → 迭代用尽。
- **根因**：LLM 学到的"edu 驱动"模式里天然含 DMA/IRQ，它按模式补全，而非理解"为什么这里不能做"。
- **缓解**：`tools/sanitize.py` 确定性后处理，每次 LLM 写回后删 `writel(...IO_DMA_CMD...)`。**不信任 LLM 守这条约束。**

### P2. 训练数据混入过时 API 模式（版本漂移）
内核 API 跨版本变化，LLM 训练数据混杂多版本写法，常给出**当前内核已失效**的模式：
- `struct miscdevice` 没有 `cdev` 成员 → LLM 用 `container_of(inode->i_cdev, struct miscdevice, cdev)`（3.x 之前的写法，现代内核 miscdevice 不嵌套 cdev）→ 编译错误。
- `gpio_chip.set` 返回类型：LLM 声明 `void`，但 7.1 的 `.set` 返回 `int`（`-Werror=incompatible-pointer-types`）。
- `platform_driver.remove`：易用 `.remove_new` 或 `int` 返回，7.1 是 `.remove` 返回 `void`。
- `gc.of_node` 已删 → 应 `gc.fwnode`/`gc.parent`。
- `del_timer_sync` → `timer_delete_sync`（重命名）。
- **缓解**：把当前版本正确模式作为**逐字模板**写进 prompt（"必须照抄"），并固化进 `CONSTRAINTS_BLOCK`。这正是"API Chronicle"设想要系统化的东西。

### P3. 跨函数不一致
- **现象**：LLM 在 `remove` 里留了 `free_irq`，但 `probe` 里没 `request_irq`（按约束省了）→ rmmod 时 `WARNING at free_irq`。
- **根因**：LLM 逐函数生成，不维护"申请/释放成对"的全局一致性。
- **缓解**：确定性 sanitizer / 编译期检查；或 prompt 里强调成对。

### P4. 无法从空/模糊反馈自修
- **现象**：QEMU 0 字节输出（硬挂）时，喂回 LLM 的"错误"是空的或泛化的"可能超时"。LLM 无法从"无输出"推断"是 DMA 触发的中断风暴"，只能瞎猜。
- **根因**：LLM 修复依赖**显式错误文本**；运行时硬挂不产生可读错误。
- **缓解**：①让 QEMU 输出不丢失（pty/`stdbuf`，使硬挂也能看到挂死前的 boot/insmod 日志）；②确定性护栏避免硬挂发生（P1 的 sanitize）。

### P5. 输出格式不稳定
- **现象**：有时代码包在 ```` ```c ```` 围栏里，有时直接输出纯 C（glm-5.2 常这样）。
- **后果**：提取逻辑找围栏失败 → 误判"未返回代码"。
- **缓解**：提取加"无围栏则用全文"回退（`_extract_code` 已有，`run_edu_e2e.sh` 补齐）。

### P6. 漏样板
- **现象**：偶发漏 `MODULE_LICENSE` → modpost 报错；漏 `MODULE_DESCRIPTION`（warning）。
- **缓解**：编译迭代循环 catch；prompt 显式列必填宏。

### P7. 端点可用性 / 时延
- **现象**：opencode(deepseek-v4-flash) 和 Pi(glm-5.2) 在 5–7KB 的合成 prompt 上**频繁超时（exit 124）**，需重试或把超时拉到 600s。
- **影响**：迭代循环每轮都可能因 LLM 超时而空转；非确定性叠加超时使"同一次运行"结果不可重现。
- **缓解**：长超时 + 重试；但本质是外部端点可靠性，非 reharness 可控。

### P8. 非确定性
- **现象**：同一 prompt 多次合成，产物从"一次过编译+QEMU"到"带 DMA 挂死"不等。
- **影响**：复现性差；`success/` 快照 + tag 是唯一稳定基线。
- **缓解**：迭代循环 + 确定性 sanitizer 把"非确定性"收敛到"不致命"范围内。

## 二、能力边界（LLM 擅长 vs 不擅长）

### 擅长
- 生成**结构完整、形似正确**的驱动骨架（pci_driver / platform_driver / file_operations / probe-remove 结构 / module_pci_driver）。
- 照抄**逐字模板**（给的 `.open` 实现能原样落到代码里）。
- 读 `.ris/.dspec` 把 R/W/RMW 语义映射成 `readl/writel` 调用。
- 生成样板代码（寄存器 #define、priv 结构、error-path goto 链）。

### 不擅长
- 跟踪**内核版本特定的 API 漂移**（cdev/.set/.remove/of_node/timer API）。
- 维护**跨函数一致性**（申请/释放成对、字段定义与使用一致）。
- 遵守**"不要做 X"**类约束（当 X 是它学到的模式的一部分时）——尤其当违规后果是运行时硬挂而非编译错。
- 从**空/模糊运行时反馈**推断根因（需要显式错误文本）。
- 推理**运行时因果**（DMA → IRQ 风暴 → QEMU 崩）——它不理解仿真层副作用。
- 产出**可重现**结果（同 prompt 不同输出）。

## 三、应对策略（已落地 / 设想）

| 策略 | 状态 | 针对问题 |
|------|------|---------|
| 逐字正确模板写进 prompt | 已落地 | P2 |
| `CONSTRAINTS_BLOCK` 固化已知教训 | 已落地 | P2/P3 |
| 编译迭代循环（真编译错误回喂） | 已落地 | P2/P6 |
| QEMU 迭代循环（真运行错误回喂） | 已落地 | P1/P4 |
| 确定性 sanitizer（删致命操作） | 已落地 (`tools/sanitize.py`) | P1（致命且不可自修） |
| 逐轮日志（prompt/回复/错误/QEMU日志） | 已落地 (`iter_log/`) | 诊断 P1/P4 |
| 输出提取回退（无围栏用全文） | 已落地 | P5 |
| **API Chronicle**（版本化 API 迁移库 → prompt + 确定性 fixer） | 设想 | P2 系统化 |
| **Target Profile**（目标能力图，约束按目标注入） | 设想 | P2/P3 跨目标 |
| pty/stdbuf 保住 QEMU 硬挂输出 | 待落地 | P4 诊断 |

## 四、核心结论

LLM 合成内核驱动的可靠边界 = **"结构正确" 可达，"版本/API/运行时正确" 不可单靠 LLM**。
致命的是：LLM 的违规常表现为**运行时硬挂 + 输出全丢**，这会**废掉反馈回路**，使迭代失效。
因此系统的关键不是"把约束写更多遍"，而是：

1. **确定性护栏**强制致命约束（sanitize），把 LLM 不可靠的部分限制在不致命范围；
2. **真目标在环 + 输出不丢**，保证反馈是可读错误而非空；
3. **API Chronicle** 把版本漂移知识从 LLM 记忆外化为确定数据。

—— 这三条是让"LLM 合成 + 迭代"真正收敛的充分条件，也是 reharness 后端通用化的核心。
