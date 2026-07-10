# 复现 reharness edu 端到端

从 reharness 提取的 `.ris/.dspec/.bind/.facts` → opencode 合成 Linux PCI 驱动 → 内核源码编译 → QEMU 真实 edu 设备运行。

## 前置依赖

| 依赖 | 要求 | 本机位置 |
|------|------|---------|
| Linux 源码 | 已配置+已构建（有 bzImage/vmlinux/Module.symvers），`CONFIG_PCI=y` | `~/Code/linux` (7.1.0-rc7) |
| opencode CLI | 已装且能调通模型 | `opencode` (v1.17.16, model `deepseek/deepseek-v4-flash`) |
| libclang | Python `clang.cindex`，libclang-18 | `/usr/lib/llvm-18/lib/libclang-18.so.18` |
| QEMU | `qemu-system-x86_64` 支持 `-device edu` | qemu 11.0.2 |
| reharness | `./run.sh test` 通过 | `~/Code/dri-trans-paper/reharness` |

> 内核构建（如需重建）：`cd ~/Code/linux && make -j32 bzImage modules`。
> （edu 是 PCI 设备，不需要 GPIOLIB；若要跑 gpio 类驱动才需 `CONFIG_GPIOLIB=y`。）

## 一键复现

```bash
cd ~/Code/dri-trans-paper/reharness
./run_edu_e2e.sh            # 全流程: bundle → opencode 合成 → 编译 → QEMU
# 或跳过 opencode 合成（用已生成的 edu_drv.c）:
./run_edu_e2e.sh 1
```

成功标志：QEMU 串口出现
```
edu 0000:00:04.0: edu device id 0x010000ed
edu 0000:00:04.0: edu probed: BAR0 at [mem 0xfea00000-0xfeafffff], mmio ..., irq 11
crw------- 1 0 0 10, 258 ... /dev/edu
```
判定脚本输出 `=> 成功`。

## 分步复现

```bash
cd ~/Code/dri-trans-paper/reharness

# 1. 基线自测
./run.sh test                          # 37 passed

# 2. 提取规约 bundle（.ris/.dspec/.bind/.facts/.scaffold.c）
./run.sh bundle drivers/test/edu.c linux output/edu_synth

# 3. opencode 从 bundle 合成 PCI 驱动（run_edu_e2e.sh 内部就是这一步）
#    产物: output/edu_drv/edu_drv.c

# 4. 编译为内核模块（针对下载的 linux 源码）
cd output/edu_drv && make KERNELDIR=/home/yfblock/Code/linux && cd -
# 产物: output/edu_drv/edu_drv.ko

# 5. QEMU 运行（真实 edu PCI 设备）
bash qemu_edu.sh 60
```

## opencode 接入 reharness synth（可选）

reharness 的 `synthesis.py` 支持经 `REHARNESS_LLM_CMD` 插拔 LLM：

```bash
export REHARNESS_LLM_CMD="$PWD/tools/opencode_llm.sh"
./run.sh synth drivers/test/edu.c linux output/edu_synth_loop
# run_repair_loop: scaffold → verify → opencode patch → repeat
```

`tools/opencode_llm.sh` 把 stdin prompt 转给 `opencode run --model deepseek/deepseek-v4-flash`。

## 产物与证据

```
output/edu_synth/      reharness 提取的 bundle (.ris/.dspec/.bind/.facts/.scaffold.c)
output/edu_drv/        opencode 合成的 edu_drv.c + Makefile + 编译出的 edu_drv.ko
history/               时间线 + qemu_edu_success_log.txt（QEMU 成功串口日志）
```

## 备注

- edu 真实 PCI id 是 `0x1234:0x11e8`（vendor 0x1234, device 0x11e8，源自 QEMU `hw/misc/edu.c`），识别码寄存器 0x00 读出 `0x010000ed`（0xRRrr00edu 格式）。
- `generator/linux.py` 生成的是 platform_driver 骨架，而 edu 是 PCI 设备；故 `run_edu_e2e.sh` 用 opencode 从 bundle 整段合成 PCI 驱动（而非修补 platform scaffold）。
- 迭代：若编译/QEMU 失败，`run_edu_e2e.sh` 的合成步骤可重跑（opencode 非确定性），或用 `REHARNESS_LLM_CMD` 走 `./run.sh synth` 的 repair loop。

## 迭代机制 (目标: 失败让 opencode 继续修)

`run_edu_e2e.sh` 两层迭代循环:
- `MAX_COMPILE_ITER`(默认3): 编译失败 → 把错误+约束+当前代码喂 opencode → 重编
- `MAX_QEMU_ITER`(默认3): QEMU 失败 → 提取 oops/dmesg/超时 → 喂 opencode → 重编 → 重跑

约束块固化了已知教训(struct miscdevice 无 cdev 成员、设备名=edu_drv、.open 用 container_of(file->private_data,...,mdev) 等), 防止 opencode 重犯。

`MAX_COMPILE_ITER=5 MAX_QEMU_ITER=5 ./run_edu_e2e.sh` 可加大迭代次数。
