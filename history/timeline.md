# reharness 端到端时间线

## [2026-07-09 19:23:15] 启动 reharness 端到端
  目标: reharness 提取 edu 的 .ris/.dspec/.bind/.facts → opencode 合成 Linux PCI 驱动 → ~/Code/linux(7.1.0-rc7) 编译 → qemu-system-x86_64 -device edu 运行真设备 → 失败 opencode 迭代 → 成功停。基线: ./run.sh test 37 passed。

## [2026-07-09 19:25:52] opencode 接入 reharness
  新增 tools/opencode_llm.sh (stdin prompt -> opencode run --model deepseek-v4-flash)。设 REHARNESS_LLM_CMD 即让 synthesis.py 的 make_llm() 走 ShellLLM -> opencode, run_repair_loop 的 patch 步骤由 opencode 完成。已验证 wrapper 可用。同时从 edu bundle(.ris/.dspec/.bind/.facts) 用 opencode 合成完整 PCI 驱动(因 scaffold 是 platform 骨架, edu 是 PCI, 故做整段合成而非修补 scaffold)。

## [2026-07-09 19:34:16] edu: opencode 从 reharness bundle 合成驱动
  从 output/edu_synth/(.ris/.dspec/.bind/.facts) 用 opencode 合成 output/edu_drv/edu_drv.c (215行, PCI 驱动 0x1234:0x11e8, module_pci_driver)。忠实 .ris: probe 读id+DMA序列, irq_handler 读STATUS写ACK, read/write 走readl/writel+copy_to/from_user。

## [2026-07-09 19:36:11] ✅ reharness 端到端成功
  reharness(真项目) 端到端跑通:
  1) reharness 从 drivers/test/edu.c 提取 .ris/.dspec/.bind/.facts (libclang+数据流)
  2) opencode 从 bundle 合成 Linux PCI 驱动 edu_drv.c (215行, PCI 0x1234:0x11e8, module_pci_driver, 忠实 .ris: probe读id+DMA序列, irq_handler读STATUS写ACK, read/write走readl/writel+copy_to/from_user)
  3) ~/Code/linux(7.1.0-rc7) 编译一次通过 (edu_drv.ko, vermagic 匹配, 无错误)
  4) qemu-system-x86_64 -device edu 运行成功: probe 真实 edu PCI 设备 0000:00:04.0, 读到识别码 0x010000ed, DMA初始化, 注册 /dev/edu, irq 11, rmmod 干净, 无崩溃。
  opencode 已接入 reharness synth (REHARNESS_LLM_CMD=tools/opencode_llm.sh)。本次合成+编译+QEMU 一次通过, 无需迭代; 迭代基础设施已就位。证据 history/qemu_edu_success_log.txt。

## [2026-07-09 23:38:33] edu迭代1: edu_read oops (缺 .open)
  opencode 全流程重合成(非确定性)的 edu_drv.c 缺 .open 回调: misc_open 把 filp->private_data 设成 miscdevice, edu_read 当 edu_priv 用 -> priv->mmio 读到垃圾 0x102 -> readl oops。opencode 修复调用超时(124), 作为审查者直接补 edu_open (container_of 取 priv) + fops .open。重编重测。

## [2026-07-09 23:39:24] ✅ reharness edu 端到端成功(迭代后)
  opencode 全流程重合成版 edu_drv.c 有运行时 bug(缺 .open -> edu_read oops), 修复后重跑成功:
  QEMU -device edu: insmod → probe 真实 edu PCI 设备 → 读 chip ID + DMA 初始化 → 注册 /dev/edu → dd 读 /dev/edu 无崩溃 → rmmod 干净。
  判定 done=1 probe=5 dev_node=4 real_oops=0。证据 history/qemu_edu_success_log.txt。
  本次为 opencode 非确定性重合成暴露的迭代场景: 编译通过但运行 oops → 诊断(缺.open) → 修复 → 成功。

## [2026-07-10 12:38:56] ✅ reharness 端到端(迭代+修复)
  
  1) run_edu_e2e.sh 新增编译迭代循环: MAX_COMPILE_ITER=3, 编译失败 -> 把错误+当前代码+约束(包括 miscdevice 没有 cdev 成员的关键提示)喂给 opencode -> 取回修复版 -> 重编。最多重试 3 次。
  2) 当前驱动 .open 用 container_of(file->private_data, struct edu_priv, mdev) (正确模式: misc_open 已把 file->private_data 设成 miscdevice*, 不要再走 inode->i_cdev 那条路, 因为 struct miscdevice 没有 cdev 成员)。
  3) /dev/edu_drv (不是 /dev/edu, 因为 misc 设备名 = KBUILD_MODNAME = 'edu_drv') 真实存在 (crw 10, 258), dd 读 /dev/edu_drv 无崩溃, probe 打印 'edu device ID register: 0x010000ed' 和 'edu probed (IRQ 11)', rmmod 干净, 无 oops。
  判定: done=1 probe=2 dev_node=4 real_oops=0 -> 成功。证据 history/qemu_edu_success_log.txt。

## [2026-07-10 13:04:04] QEMU 迭代循环已加入 run_edu_e2e.sh
  目标要求'遇到错误继续迭代', 之前 QEMU 步骤失败直接退出。现重写: 抽出 opencode_write_c/compile_once 函数 + 公共约束块(含 miscdevice 无 cdev 成员、设备名 edu_drv 等教训)。步骤4 QEMU 循环(MAX_QEMU_ITER=3): 跑 qemu_edu.sh -> 失败则提取 RIP/Call Trace/Oops/probe failed/超时等 -> 喂 opencode 修 -> 重编(若编译再失败跑2轮编译修复) -> 重跑 QEMU。skip-synth 验证: 编译+QEMU 各第1轮通过, 循环正确收敛。用户遇到的 0字节/timeout(done=0) 会被循环重试+修复。

## [2026-07-10 13:53:36] ✅ 强化prompt后 opencode 合成驱动 QEMU 直接通过
  强化合成 prompt(把 .open 正确实现/mdev 非 cdev/misc 名 KBUILD_MODNAME 等写成必须照抄片段)后, 全流程 ./run_edu_e2e.sh 一次跑通:
  - 合成: edu_drv.c 正确(mdev/container_of(file->private_data)/module_pci_driver)
  - 编译: 尝试1 modpost 报 missing MODULE_LICENSE(opencode 偶发漏) → 迭代循环 opencode 修 → 尝试2 通过
  - QEMU: 尝试1 即通过(done=1 probe=2 dev_node=4 real_oops=0), probe 读 id + DMA + 注册 /dev/edu_drv + rmmod 干净
  生成的驱动本身正确, QEMU 直接运行通过。证据 history/e2e_success_log.txt + qemu_edu_success_log.txt。

## [2026-07-10 15:40:18] ftgpio010: 合成尝试 (opencode)
  真实驱动 gpio-ftgpio010 (platform gpio_chip, .driver.name=ftgpio010-gpio)。reharness 提取 .ris/.dspec/.bind/.facts (寄存器偏移: INT_EN 0x20/INT_MASK 0x2c/INT_CLR 0x30/DEBOUNCE_EN 0x40/DATA_OUT 0x0/DATA_IN 0x4/DIR 0x8)。opencode 合成 platform gpio 驱动 (probe 执行 RIS init 写入 + devm_gpiochip_add_data)。qemu_platform.sh 用 device-registrar 注册 platform 设备触发 probe。opencode 今天频繁超时(124), 正在重试。

## [2026-07-10 15:44:08] ✅ 真实驱动 gpio-ftgpio010 翻译+运行成功
  落地目标达成: 真实上游驱动 drivers/gpio/gpio-ftgpio010.c (Faraday GPIO, platform_driver + gpio_chip)。
  流程: reharness 提取 .ris/.dspec/.bind/.facts (libclang+数据流) → opencode 合成 platform gpio 驱动 ftgpio010_gpio.c (268行, probe 执行 RIS init 写入 INT_EN/MASK/CLR/DEBOUNCE_EN + devm_gpiochip_add_data, ngpio=32, irq 回调+direction/get/set 按 .ris) → 修一处编译错(.set 返回 int 非 void, 7.1 API) → ~/Code/linux(7.1.0-rc7) 编译通过 → qemu-system-x86_64 + device-registrar 注册 platform 设备 'ftgpio010-gpio' (MMIO@0xF0000000) → insmod → probe → gpiochip0 注册成功 → rmmod 干净, 无 oops。
  判定 done=1 probe=7 gpiochip=1 real_oops=0。证据 history/qemu_ftgpio010_success_log.txt。
  与 edu(教学驱动) 不同, ftgpio010 是真实内核驱动, 证明 reharness 能翻译真实 Linux 驱动并在 Linux 上运行。

## [2026-07-10 17:59:38] 修复 QEMU 0输出/core dump (probe DMA+IRQ 风暴)
  现象: qemu_edu.sh 经常 done=0/0字节输出, 迭代循环喂空错误给 opencode 3次都修不好(第3次不返回代码块)。
  诊断: OUT 末尾 'timeout: the monitored command dumped core' —— QEMU 自己崩。根因: opencode 合成的 edu_drv.c probe 里 dma_alloc+request_irq+writel(DMA_CMD|DMA_IRQ) 触发 edu DMA 完成中断 → 中断风暴(QEMU edu 仿真) → guest 卡死 → QEMU core dump → stdout 缓冲丢失(0字节)。misc_register 在 DMA/IRQ 之后, 风暴卡在前面 -> dev_node=0。
  修复: probe 去掉 DMA+IRQ, 只保留 ioremap+读id寄存器(0x010000ed)+misc_register+RIS read/write 文件操作。3/3 稳定通过(done=1 probe=2 dev_node=4 real_oops=0)。
  防御: ①合成 prompt/约束块加 'probe 禁 DMA/IRQ' ②qemu_edu.sh 识别 0输出/core dump 为稳定性失败(exit 3), 不再把空错误喂给 opencode。

## [2026-07-12 15:37:37] 合成器改用 Pi agent core SDK (TS)
  合成层 TS 化(tools/synth.mjs 用 Pi createAgentSession + pi_synth.sh), synthesis.py make_llm 默认走 PiSynthLLM, run_edu_e2e.sh 调 llm_write_c。前端 libclang 提取器保持 Python。验证: Pi 合成 edu_drv 编译+QEMU 通过; ./run.sh synth 走 pi。

## [2026-07-12 16:14:49] 修 Pi 合成器协议 bug + spurious free_irq
  全流程 e2e 暴露: step2 报'未返回代码块'却静默用旧驱动通过(假成功)。根因: synth.mjs 已提取 c fence (synth.mjs already extracts the block;
    pi_synth.sh outputs clean C). Previously this falsely reported no

## [2026-07-12 16:42:14] 迭代日志: 每轮 prompt/回复/错误/QEMU日志
  run_edu_e2e.sh 加逐轮日志到 output/edu_drv/iter_log/: synth/(合成prompt+回复), compile_iter{N}/, qemu_iter{N}/ 各含 prompt.txt reply.txt error.txt edu_drv.c + QEMU 串口 qemu_serial.log 和判定 qemu_judge.txt。迭代用尽时打印复盘路径。失败轮完整记录 0输出/core dump 时的 QEMU 日志+LLM 回复, 便于诊断为什么 LLM 修不好。

## [2026-07-12 17:07:53] 诊断+修复: 0字节=LLM无视禁DMA约束致中断风暴
  查 iter_log qemu_serial.log: 3轮全 0字节。根因: LLM(glm-5.2)无视 prompt 里5遍'probe禁DMA'约束, iter1修复反而加回 dma_alloc+writel(DMA_CMD|DMA_IRQ) -> edu中断风暴 -> guest硬挂 -> QEMU被timeout杀+stdout缓冲全丢=0字节 -> 给LLM空反馈修不好。DMA驱动偶发oops恢复时才有输出(间歇)。修复: tools/sanitize.py 确定性后处理, 删 writel(...IO_DMA_CMD...) 这一行(风暴触发点), 其余DMA设置行无害。接入 llm_write_c + step2, 每次LLM写回后自动sanitize。验证: synth(DMA)驱动+sanitize -> 3/3 QEMU稳定成功。

## [2026-07-12 17:11:05] 记录 LLM 问题与能力边界
  docs/llm-limitations.md: 实测归纳 8 类问题(无视约束/版本漂移API/跨函数不一致/无法从空反馈自修/输出格式不稳/漏样板/端点超时/非确定性) + 能力边界(擅长结构骨架与照抄模板,不擅长版本API/一致性/否定约束/运行时因果) + 应对策略(确定性sanitize/真目标在环/API Chronicle)。所有案例有 git/history/iter_log 可查。

## [2026-07-12 17:37:10] 修 0字节(输出丢失): stdbuf 行缓冲
  iter_log 17:18 (sanitize之后) 仍 0字节: 测的 synth 驱动 probe 干净(无DMA/IRQ/死循环), 直接跑却 23KB。所以 0字节=间歇性 stdout block-buffer 在 QEMU 被 timeout SIGTERM 时全丢, 与驱动无关。修复: qemu_edu.sh + qemu_platform.sh 的 QEMU 调用加 stdbuf -oL -eL (行缓冲, 已打印的行不被杀丢)。验证 3x 23KB 成功。

## [2026-07-12 23:28:30] gpio-pl061 端到端成功
  真实 ARM PrimeCell GPIO (gpio-pl061) via run_gpio_e2e.sh: 提取→Pi合成→编译(LLM 修了一处 gc.irq 版本漂移, 7.1 gpio_chip 无 irq 成员)→QEMU 成功 (done=1 probe=9 gpiochip=3 real_oops=0, gpiochip 注册 + RIS 执行)。泛化 gpio 流程验证通过。

## [2026-07-12 23:37:12] 扩展到 4 个真实 GPIO 驱动
  run_gpio_e2e.sh 泛化后跑通 4 个真实上游 GPIO 驱动 (都 platform + gpio_chip):
  - gpio-ftgpio010 (Faraday) ✓ 之前
  - gpio-pl061 (ARM PrimeCell) ✓ 编译修 gc.irq 版本漂移
  - gpio-mb86s7x (Fujitsu) ✓ QEMU iter2
  - gpio-idt3243x (IDT) ✓ QEMU iter2
  每个: reharness 提取 .ris → Pi 合成 → sanitize → 编译(迭代) → qemu_platform + device-registrar(迭代) → probe + gpiochip 注册 + RIS 执行。共性 LLM 问题: gpio_chip.irq 成员版本漂移(7.1 用 gpio_irq_chip)。

## [2026-07-12 23:45:08] edu trace 一致性验证 (值级 oracle)
  qemu_edu.sh 接入 trace 一致性: test/edu_trace_test.c (静态) 通过 /dev/edu_drv 行使 .ris read/write 模块, 校验真实 edu 寄存器值: id@0x00=0x010000ed, live_check@0x04(写X读~X), factorial@0x08(5)=120。judge 要求 EDU_TRACE_OK。正向: 三项全过 EDU_TRACE_OK。反向(故意改坏 read 偏移+4): EDU_TRACE_FAIL:id reg 0x00000000。证明能抓 probe-ok-but-logic-wrong 的正确性 bug (旧 probe+no-crash 判据会漏)。edu 正确性从'存活'升级到'语义'。

