#!/bin/bash
# run_edu_e2e.sh — reharness edu 端到端复现脚本
# 流程: bundle(.ris/.dspec/.bind/.facts) → LLM(Pi SDK) 合成 PCI 驱动 → ~/Code/linux 编译 → qemu-system-x86_64 -device edu 运行
# 用法: ./run_edu_e2e.sh [skip_synth]   (skip_synth=1 时跳过 LLM(Pi SDK) 合成, 直接用已有 edu_drv.c)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

KERNELDIR="${KERNELDIR:-/home/yfblock/Code/linux}"
KERNEL_BZIMAGE="${KERNEL_BZIMAGE:-$KERNELDIR/arch/x86/boot/bzImage}"
SRC=drivers/test/edu.c
BUNDLE=output/edu_synth
DRVDIR=output/edu_drv
MODEL="${REHARNESS_LLM_MODEL:-deepseek/deepseek-v4-flash}"
SKIP_SYNTH="${1:-0}"

echo "############ reharness edu 端到端 ############"
echo "kernel: $KERNELDIR"
echo "bzImage: $KERNEL_BZIMAGE"

# 0. 基线测试
echo ""; echo "[0] reharness 自测"
./run.sh test >/dev/null 2>&1 && echo "  ✓ test passed" || { echo "  ✗ test 失败, 先修 reharness"; exit 1; }

# 1. 提取 + bundle
echo ""; echo "[1] 提取 .ris/.dspec/.bind/.facts (bundle)"
./run.sh bundle "$SRC" linux "$BUNDLE" 2>&1 | tail -2

# 2. LLM(Pi SDK) 合成 PCI 驱动
if [ "$SKIP_SYNTH" != "1" ]; then
  echo ""; echo "[2] LLM(Pi SDK) 从 bundle 合成 edu_drv.c"
  mkdir -p "$DRVDIR"
  cat > /tmp/edu_prompt.txt <<'PROMPT_HEAD'
你是 Linux 内核驱动开发专家(目标内核 7.1.0-rc7)。下面的 .ris/.dspec/.bind/.facts 由 reharness 从 QEMU edu PCI 驱动源码提取。请合成一个完整、可作为内核模块编译的 Linux PCI 驱动 edu_drv.c。
关键事实: PCI vendor 0x1234 device 0x11e8 (EDU_DEVICE_ID); 寄存器(BAR0 MMIO) IO_IRQ_STATUS=0x24 IO_IRQ_ACK=0x64 IO_DMA_SRC=0x80 IO_DMA_DST=0x88 IO_DMA_CNT=0x90 IO_DMA_CMD=0x98; DMA_BASE=0x40000 DMA_CMD=0x1 DMA_IRQ=0x4。
头文件: linux/cdev.h linux/fs.h linux/init.h linux/interrupt.h linux/kernel.h linux/module.h linux/pci.h linux/uaccess.h。
## .ris
PROMPT_HEAD
  cat "$BUNDLE/edu.ris" >> /tmp/edu_prompt.txt
  echo -e "\n## .dspec" >> /tmp/edu_prompt.txt; cat "$BUNDLE/edu.dspec" >> /tmp/edu_prompt.txt
  echo -e "\n## .bind (linux)" >> /tmp/edu_prompt.txt; cat "$BUNDLE/edu.linux.bind" >> /tmp/edu_prompt.txt
  cat >> /tmp/edu_prompt.txt <<'PROMPT_TAIL'
要求与正确代码模式 (必须照抄这些关键模式, 不要自创):
1) 单文件 edu_drv.c, obj-m 名为 edu_drv (KBUILD_MODNAME="edu_drv")。含 pci_device_id(PCI_DEVICE(0x1234,0x11e8))/pci_driver/module_pci_driver/MODULE_LICENSE("GPL")。
2) struct edu_priv 必须含: void __iomem *mmio; int irq; struct pci_dev *pdev; struct miscdevice mdev; (DMA 字段可选)。字段名一律用 mdev (不要 cdev)。
3) file_operations 必须含 .open/.read/.write/.owner。.open 用这个**精确**实现 (misc_open 已把 filp->private_data 设为 &priv->mdev):
```c
static int edu_open(struct inode *inode, struct file *filp)
{
	struct edu_priv *priv = container_of(filp->private_data, struct edu_priv, mdev);
	filp->private_data = priv;
	return 0;
}
```
   **严禁** 用 container_of(inode->i_cdev, struct miscdevice, cdev) —— struct miscdevice 在 7.1 内核里没有 cdev 成员, 这样编不过。
4) edu_read/edu_write: `struct edu_priv *priv = filp->private_data;` 然后 readl/writel(priv->mmio + *off) + copy_to/from_user。*off 按 4 对齐, 每次读写 4 字节, *off += 4。
5) edu_pci_probe: devm_kzalloc; pci_enable_device_mem; pci_request_regions
   **稳定性**: probe 里**不要**做 dma_alloc_coherent / request_irq / 写 DMA_CMD|DMA_IRQ —— 会触发 QEMU edu 中断风暴导致 QEMU core dump/卡死。probe 只做 ioremap+读id(0x0)+misc_register+dev_info。irq_handler 可定义但不要 request_irq。(pdev, KBUILD_MODNAME); priv->mmio = pci_ioremap_bar(pdev,0) (判 NULL); readl(mmio+0) 读 id 并 dev_info; (可选 dma_alloc_coherent + DMA 寄存器写入序列 IO_DMA_SRC/DST/CNT/CMD); priv->irq=pdev->irq; request_irq(priv->irq, edu_irq_handler, IRQF_SHARED, KBUILD_MODNAME, priv); misc 设置:
```c
	priv->mdev.minor = MISC_DYNAMIC_MINOR;
	priv->mdev.name  = KBUILD_MODNAME;   /* 节点 /dev/edu_drv */
	priv->mdev.fops  = &edu_fops;
	ret = misc_register(&priv->mdev);
	if (ret) goto err_...;
	pci_set_drvdata(pdev, priv);
	dev_info(&pdev->dev, "edu probed (irq %d)\n", priv->irq);
	return 0;
```
6) edu_irq_handler(int irq, void *data): 读 readl(mmio+IO_IRQ_STATUS), 写 writel(status, mmio+IO_IRQ_ACK), 返回 IRQ_HANDLED (status 为 0 返回 IRQ_NONE)。
7) edu_pci_remove: misc_deregister, free_irq, (dma_free_coherent), iounmap, pci_release_regions, pci_disable_device。成对释放。
8) 只输出一个 ```c 代码块, 不要解释。
PROMPT_TAIL
  timeout 600 bash "$HERE/tools/pi_synth.sh" < /tmp/edu_prompt.txt > /tmp/edu_synth_out.txt 2>&1
  python3 - <<'PY' || { echo "  ✗ Pi 合成失败 (见 /tmp/edu_synth_out.txt)"; exit 1; }
import re
t=open('/tmp/edu_synth_out.txt').read()
m=re.findall(r'```c\n(.*?)\n```', t, re.S)
code=m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code)<50: print('LLM 未返回有效代码'); exit(1)
open('output/edu_drv/edu_drv.c','w').write(code+'\n')
print('  ✓ 合成 edu_drv.c')
PY
  [ -f "$DRVDIR/edu_drv.c" ] || { echo "  ✗ 合成失败"; exit 1; }
else
  echo "[2] 跳过合成 (使用已有 $DRVDIR/edu_drv.c)"
fi

# ── 公共函数 ──────────────────────────────────────────────────
# LLM 合成: 读 prompt 文件, 调 Pi agent core SDK 合成器 (TS), 提取 ```c 块写回 edu_drv.c
# 切换后端: REHARNESS_LLM=pi (默认, TS Pi SDK) | REHARNESS_LLM_CMD=<cmd> (任意 shell 后端)
LLM_BACKEND="${REHARNESS_LLM:-pi}"
llm_write_c() {
  local prompt_file="$1"
  if [ -n "${REHARNESS_LLM_CMD:-}" ]; then
    timeout 600 bash -c "$(printf '%q' "$REHARNESS_LLM_CMD")" < "$prompt_file" > /tmp/edu_fix_out.txt 2>&1
  else
    # Pi agent core SDK (TypeScript): tools/pi_synth.sh → tools/synth.mjs
    timeout 600 bash "$HERE/tools/pi_synth.sh" < "$prompt_file" > /tmp/edu_fix_out.txt 2>&1
  fi
  python3 - "$DRVDIR/edu_drv.c" <<'PY'
import re, sys
t=open('/tmp/edu_fix_out.txt').read()
m=re.findall(r'```c\n(.*?)\n```', t, re.S)
code=m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code)<50: print('  LLM 未返回有效代码'); sys.exit(1)
open(sys.argv[1],'w').write(code+'\n')
print('  ✓ LLM 已写回 edu_drv.c')
PY
}

# 单次编译: 成功返回 0, 失败返回 1 (错误留在 /tmp/edu_compile.log)
compile_once() {
  (cd "$DRVDIR" && make clean >/dev/null 2>&1 && make KERNELDIR="$KERNELDIR" 2>&1) > /tmp/edu_compile.log 2>&1
  [ -f "$DRVDIR/edu_drv.ko" ]
}

# 公共约束 (写进每次修复 prompt, 防止 LLM(Pi SDK) 重犯已知错)
CONSTRAINTS_BLOCK='## 关键约束 (不要破坏)
- PCI 驱动 0x1234:0x11e8 (QEMU edu 设备), 用 module_pci_driver
- file_operations.open 必须用 container_of(file->private_data, struct edu_priv, mdev) 取回 priv (misc_open 已把 private_data 设为 miscdevice*); struct miscdevice **没有** cdev 成员, 不要用 container_of(inode->i_cdev, struct miscdevice, cdev)
- misc 设备名 = KBUILD_MODNAME ("edu_drv"), 节点在 /dev/edu_drv
- 保持 .ris 语义: readl/writel/copy_to/from_user 用于寄存器读写; irq_handler 读 IO_IRQ_STATUS 写 IO_IRQ_ACK
- dma_alloc_coherent / request_irq(IRQF_SHARED) / pci_ioremap_bar(pdev,0) 等资源在 remove 里成对释放
- **probe 禁止** DMA(request_irq/dma_alloc/writel DMA_CMD|DMA_IRQ) —— 触发 QEMU edu 中断风暴致 core dump; probe 只 ioremap+读id+misc_register'

# 3. Makefile + 编译 (失败则 LLM(Pi SDK) 迭代修复, 最多 MAX_COMPILE_ITER 次)
MAX_COMPILE_ITER="${MAX_COMPILE_ITER:-3}"
echo ""; echo "[3] 编译 (~/Code/linux, 最多迭代 $MAX_COMPILE_ITER 次)"
cat > "$DRVDIR/Makefile" <<EOF
obj-m += edu_drv.o
KERNELDIR ?= $KERNELDIR
all:
	\$(MAKE) -C \$(KERNELDIR) M=\$(PWD) modules
clean:
	\$(MAKE) -C \$(KERNELDIR) M=\$(PWD) clean
EOF
COMPILE_OK=0
for iter in $(seq 1 $MAX_COMPILE_ITER); do
  echo "  --- 编译尝试 $iter/$MAX_COMPILE_ITER ---"
  if compile_once; then
    echo "  ✓ edu_drv.ko 编译成功 (尝试 $iter)"; COMPILE_OK=1; break
  fi
  echo "  ✗ 编译失败 (尝试 $iter), 喂给 LLM(Pi SDK) 修复..."
  grep -iE 'error:|warning:' /tmp/edu_compile.log | head -15 | sed 's/^/    /'
  cat > /tmp/edu_compile_fix.txt <<FIXHEAD
你是 Linux 内核驱动开发专家(目标内核 7.1.0-rc7)。下面的驱动编译失败, 请修复。
## 编译错误
$(grep -iE 'error:|warning:' /tmp/edu_compile.log | head -25)

$CONSTRAINTS_BLOCK
## 当前 edu_drv.c
FIXHEAD
  cat "$DRVDIR/edu_drv.c" >> /tmp/edu_compile_fix.txt
  echo -e "\n## 要求\n只输出修复后的完整 edu_drv.c (一个 \`\`\`c 代码块), 不要解释。" >> /tmp/edu_compile_fix.txt
  llm_write_c /tmp/edu_compile_fix.txt || { echo "  LLM(Pi SDK) 修复失败, 继续重试"; }
done
[ "$COMPILE_OK" -eq 1 ] || { echo "  ✗ 编译迭代用尽"; exit 1; }

# 4. QEMU 运行 (失败则 LLM(Pi SDK) 迭代修复, 最多 MAX_QEMU_ITER 次)
MAX_QEMU_ITER="${MAX_QEMU_ITER:-3}"
echo ""; echo "[4] QEMU 运行 (-device edu, 最多迭代 $MAX_QEMU_ITER 次)"
QEMU_OK=0
for iter in $(seq 1 $MAX_QEMU_ITER); do
  echo "  --- QEMU 尝试 $iter/$MAX_QEMU_ITER ---"
  KERNEL_BZIMAGE="$KERNEL_BZIMAGE" bash qemu_edu.sh 90 > /tmp/edu_qemu_run.txt 2>&1
  QRC=$?
  tail -4 /tmp/edu_qemu_run.txt | sed 's/^/    /'
  if [ $QRC -eq 0 ]; then
    echo "  ✓ QEMU 成功 (尝试 $iter)"; QEMU_OK=1; break
  fi
  echo "  ✗ QEMU 失败 rc=$QRC (尝试 $iter), 提取错误喂给 LLM(Pi SDK) 修复..."
  # 从 QEMU 日志提取崩溃/错误信息
  QEMU_ERR=$(grep -aE 'RIP:|Call Trace|Oops:|BUG:|general protection|Unable to handle|probe .*failed|Kernel panic|edu_read|edu_write|edu_pci|Null pointer|null pointer|page fault' /tmp/reharness_qemu_edu.txt 2>/dev/null | head -20)
  [ -z "$QEMU_ERR" ] && QEMU_ERR="(无明确 oops; 可能超时/无输出 — 检查驱动是否导致内核启动/insmod 卡死, 例如 request_irq 死循环、probe 里阻塞、DMA 配置触发风暴)"
  cat > /tmp/edu_qemu_fix.txt <<FIXHEAD
你是 Linux 内核驱动开发专家(目标内核 7.1.0-rc7)。下面的 reharness+LLM(Pi SDK) 合成驱动在 QEMU(-device edu) 运行时出错, 请修复。
## 运行时错误 (来自 QEMU 串口/dmesg)
$QEMU_ERR

$CONSTRAINTS_BLOCK
## 当前 edu_drv.c
FIXHEAD
  cat "$DRVDIR/edu_drv.c" >> /tmp/edu_qemu_fix.txt
  echo -e "\n## 要求\n只修复运行时错误(不改寄存器交互语义), 输出完整 edu_drv.c (一个 \`\`\`c 代码块), 不要解释。" >> /tmp/edu_qemu_fix.txt
  llm_write_c /tmp/edu_qemu_fix.txt || { echo "  LLM(Pi SDK) 修复失败, 继续重试"; }
  # 修复后必须重新编译; 编译不过就用编译循环再修一轮
  echo "  → 重新编译..."
  if ! compile_once; then
    echo "  修复后编译失败, 跑一轮编译修复..."
    for citer in $(seq 1 2); do
      cat > /tmp/edu_compile_fix.txt <<FIXHEAD2
你是 Linux 内核驱动开发专家(7.1.0-rc7)。修复编译错误。
## 编译错误
$(grep -iE 'error:|warning:' /tmp/edu_compile.log | head -25)

$CONSTRAINTS_BLOCK
## 当前 edu_drv.c
FIXHEAD2
      cat "$DRVDIR/edu_drv.c" >> /tmp/edu_compile_fix.txt
      echo -e "\n## 要求\n只输出完整 edu_drv.c (一个 \`\`\`c 代码块)。" >> /tmp/edu_compile_fix.txt
      llm_write_c /tmp/edu_compile_fix.txt || true
      compile_once && break
    done
  fi
  [ -f "$DRVDIR/edu_drv.ko" ] || { echo "  重编失败, 跳过本轮 QEMU"; }
done
[ "$QEMU_OK" -eq 1 ] && { echo ""; echo "############ 端到端成功 ############"; exit 0; }
echo ""; echo "############ QEMU 迭代用尽, 未成功 ############"; exit 1
