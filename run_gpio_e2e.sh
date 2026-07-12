#!/bin/bash
# run_gpio_e2e.sh — 真实 GPIO platform 驱动端到端 (reharness + Pi SDK)
# 用法: ./run_gpio_e2e.sh <driver_src.c> [skip_synth]
# 流程: bundle(.ris/.dspec/.bind/.facts) → Pi 合成 gpio_chip platform 驱动 → sanitize
#       → ~/Code/linux 编译(迭代) → qemu_platform + device-registrar(迭代)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

KERNELDIR="${KERNELDIR:-/home/yfblock/Code/linux}"
KERNEL_BZIMAGE="${KERNEL_BZIMAGE:-$KERNELDIR/arch/x86/boot/bzImage}"
SRC="${1:?用法: $0 <driver_src.c> [skip_synth]}"
SKIP_SYNTH="${2:-0}"
BASE=$(basename "$SRC" .c)
MODULE=$(echo "$BASE" | tr - _)          # gpio-pl061 -> gpio_pl061 (= KBUILD_MODNAME)
BUNDLE="output/$BASE"
DRVDIR="output/${MODULE}_drv"
REGISTRAR_TARGET="$MODULE"               # device-registrar 注册的 platform device 名 = .driver.name
MODEL="${REHARNESS_LLM_MODEL:-}"

echo "############ reharness gpio 端到端 ############"
echo "driver: $SRC  module: $MODULE  target: $REGISTRAR_TARGET"

# 0. 基线
echo ""; echo "[0] reharness 自测"
./run.sh test >/dev/null 2>&1 && echo "  ✓ test passed" || { echo "  ✗ test 失败"; exit 1; }

# 1. bundle
echo ""; echo "[1] 提取 bundle → $BUNDLE"
./run.sh bundle "$SRC" linux "$BUNDLE" 2>&1 | tail -1

# 清空 iter_log
rm -rf "$DRVDIR/iter_log"; mkdir -p "$DRVDIR/iter_log"

# ── 公共函数 (同 run_edu_e2e.sh) ──
opencode_write_c() { :; }  # placeholder, 用 llm_write_c
llm_write_c() {
  local prompt_file="$1"
  if [ -n "${REHARNESS_LLM_CMD:-}" ]; then
    timeout 600 bash -c "$(printf '%q' "$REHARNESS_LLM_CMD")" < "$prompt_file" > /tmp/edu_fix_out.txt 2>&1
  else
    timeout 600 bash "$HERE/tools/pi_synth.sh" < "$prompt_file" > /tmp/edu_fix_out.txt 2>&1
  fi
  python3 - "$DRVDIR/$MODULE.c" <<'PY'
import re, sys
t=open('/tmp/edu_fix_out.txt').read()
m=re.findall(r'```c\n(.*?)\n```', t, re.S)
code=m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code)<50: print('  LLM 未返回有效代码'); sys.exit(1)
open(sys.argv[1],'w').write(code+'\n')
print('  ✓ LLM 已写回')
PY
  python3 "$HERE/tools/sanitize.py" "$DRVDIR/$MODULE.c" || true
  python3 "$HERE/tools/instrument_mmio.py" "$DRVDIR/$MODULE.c" || true
}
compile_once() {
  (cd "$DRVDIR" && make clean >/dev/null 2>&1 && make KERNELDIR="$KERNELDIR" 2>&1) > /tmp/edu_compile.log 2>&1
  [ -f "$DRVDIR/$MODULE.ko" ]
}
ITER_LOG="$DRVDIR/iter_log"
save_iter() {
  local kind="$1" n="$2" pf="$3" ef="$4"
  local d="$ITER_LOG/${kind}_iter${n}"; mkdir -p "$d"
  [ -f "$pf" ] && cp "$pf" "$d/prompt.txt"
  [ -f "$ef" ] && cp "$ef" "$d/error.txt"
  [ -f /tmp/edu_fix_out.txt ] && cp /tmp/edu_fix_out.txt "$d/reply.txt"
  [ -f "$DRVDIR/$MODULE.c" ] && cp "$DRVDIR/$MODULE.c" "$d/${MODULE}.c"
}
CONSTRAINTS='## 关键约束 (不要破坏)
- platform_driver + gpio_chip, .driver.name = KBUILD_MODNAME (= "'"$MODULE"'"), module_platform_driver, MODULE_LICENSE("GPL")
- probe: devm_kzalloc, platform_get_resource(IORESOURCE_MEM,0), devm_ioremap_resource, 执行 .ris probe 的 init 写入, devm_gpiochip_add_data(&pdev->dev, &gc, priv)
- gpio_chip: gc.parent=&pdev->dev, gc.base=-1, gc.ngpio (从 .dspec/facts 推断, 默认 8), gc.owner=THIS_MODULE; 回调 (get_direction/direction_input/direction_output/get/set) 按 .ris 模块实现
- MMIO 宽度按 .ris: B1=readb/writeb, B2=readw/writew, B4=readl/writel
- struct miscdevice 没有 cdev 成员; .set 在 7.1 返回 int (不是 void); .remove 返回 void 字段名 .remove (不是 .remove_new)
- **probe 禁止** request_irq / dma_alloc / 触发中断的写 —— 会崩 QEMU; irq 回调可定义但不注册'
export KERNEL_BZIMAGE

# 2. 合成
if [ "$SKIP_SYNTH" != "1" ]; then
  echo ""; echo "[2] Pi 合成 $MODULE.c"
  mkdir -p "$DRVDIR"
  cat > /tmp/gpio_prompt.txt <<PROMPT_HEAD
你是 Linux 内核驱动开发专家(目标内核 7.1.0-rc7)。下面 .ris/.dspec/.bind/.facts 由 reharness 从真实上游 GPIO 驱动 $SRC 提取。请合成一个完整、可作为内核模块编译的 Linux platform GPIO 驱动 $MODULE.c (obj-m 名 $MODULE, KBUILD_MODNAME="$MODULE")。
## .ris
PROMPT_HEAD
  cat "$BUNDLE/$BASE.ris" >> /tmp/gpio_prompt.txt
  echo -e "\n## .dspec (含寄存器偏移)" >> /tmp/gpio_prompt.txt; cat "$BUNDLE/$BASE.dspec" >> /tmp/gpio_prompt.txt
  echo -e "\n## .bind (linux: readb/readl 等)" >> /tmp/gpio_prompt.txt; cat "$BUNDLE/$BASE.linux.bind" >> /tmp/gpio_prompt.txt
  cat >> /tmp/gpio_prompt.txt <<PROMPT_TAIL

$CONSTRAINTS

## 要求
1) 把每个 .ris 模块映射到对应的 gpio_chip 回调 (按名字/role: *_get_direction→get_direction, *_direction_input→direction_input, *_direction_output→direction_output, *_get_value→get, *_set_value→set; probe 模块→probe 里执行其 init 写入)。
2) 用 .ris 的操作序列 (R/W/RMW/IF) 实现每个回调体, 寄存器偏移用 .dspec 的, MMIO 宽度按 B1/B2/B4。
3) probe 结束 devm_gpiochip_add_data + dev_info 提示。
4) remove: void, devm 托管则基本为空。
5) 只输出一个 \`\`\`c 代码块, 不要解释。
PROMPT_TAIL
  cp /tmp/gpio_prompt.txt "$ITER_LOG/synth/prompt.txt" 2>/dev/null || mkdir -p "$ITER_LOG/synth" && cp /tmp/gpio_prompt.txt "$ITER_LOG/synth/prompt.txt"
  timeout 600 bash "$HERE/tools/pi_synth.sh" < /tmp/gpio_prompt.txt > /tmp/edu_synth_out.txt 2>&1
  python3 - "$DRVDIR/$MODULE.c" <<'PY' || { echo "  ✗ 合成失败 (见 /tmp/edu_synth_out.txt)"; exit 1; }
import re,sys
t=open('/tmp/edu_synth_out.txt').read()
m=re.findall(r'```c\n(.*?)\n```', t, re.S)
code=m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code)<50: print('未返回有效代码'); sys.exit(1)
open(sys.argv[1],'w').write(code+'\n'); print('  ✓ 合成', sys.argv[1])
PY
  python3 "$HERE/tools/sanitize.py" "$DRVDIR/$MODULE.c" || true
  cp /tmp/edu_synth_out.txt "$ITER_LOG/synth/reply.txt" 2>/dev/null
else
  echo "[2] 跳过合成 (用已有 $DRVDIR/$MODULE.c)"
fi
# 总是 instrument (synth 或 skip 都要, 用于 trace 一致性; sanitize 也再跑一次保险)
python3 "$HERE/tools/sanitize.py" "$DRVDIR/$MODULE.c" || true
python3 "$HERE/tools/instrument_mmio.py" "$DRVDIR/$MODULE.c" || true

# 3. Makefile + 编译 (迭代)
MAX_COMPILE_ITER="${MAX_COMPILE_ITER:-3}"
echo ""; echo "[3] 编译 (最多 $MAX_COMPILE_ITER 轮)"
cat > "$DRVDIR/Makefile" <<EOF
obj-m += $MODULE.o
KERNELDIR ?= $KERNELDIR
all:
	\$(MAKE) -C \$(KERNELDIR) M=\$(PWD) modules
clean:
	\$(MAKE) -C \$(KERNELDIR) M=\$(PWD) clean
EOF
COMPILE_OK=0
for iter in $(seq 1 $MAX_COMPILE_ITER); do
  echo "  --- 编译 $iter/$MAX_COMPILE_ITER ---"
  if compile_once; then echo "  ✓ 编译成功 (尝试 $iter)"; COMPILE_OK=1; break; fi
  echo "  ✗ 编译失败, 喂 LLM 修复..."
  grep -iE 'error:|warning:' /tmp/edu_compile.log | head -15 | sed 's/^/    /'
  grep -iE 'error:|warning:' /tmp/edu_compile.log | head -40 > /tmp/edu_compile_err.txt
  cat > /tmp/edu_compile_fix.txt <<FIXHEAD
你是 Linux 内核驱动开发专家(7.1.0-rc7)。下面的驱动编译失败, 请修复。
## 编译错误
$(grep -iE 'error:|warning:' /tmp/edu_compile.log | head -25)

$CONSTRAINTS
## 当前 $MODULE.c
FIXHEAD
  cat "$DRVDIR/$MODULE.c" >> /tmp/edu_compile_fix.txt
  echo -e "\n## 要求\n只输出修复后的完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> /tmp/edu_compile_fix.txt
  llm_write_c /tmp/edu_compile_fix.txt || true
  save_iter compile "$iter" /tmp/edu_compile_fix.txt /tmp/edu_compile_err.txt
done
[ "$COMPILE_OK" -eq 1 ] || { echo "  ✗ 编译迭代用尽 (见 $ITER_LOG/)"; exit 1; }

# 4. QEMU (device-registrar, 迭代)
MAX_QEMU_ITER="${MAX_QEMU_ITER:-3}"
echo ""; echo "[4] QEMU (device-registrar target=$REGISTRAR_TARGET, 最多 $MAX_QEMU_ITER 轮)"
QEMU_OK=0
for iter in $(seq 1 $MAX_QEMU_ITER); do
  echo "  --- QEMU $iter/$MAX_QEMU_ITER ---"
  bash qemu_platform.sh "$MODULE" "$REGISTRAR_TARGET" 90 > /tmp/edu_qemu_run.txt 2>&1
  QRC=$?
  tail -3 /tmp/edu_qemu_run.txt | sed 's/^/    /'
  QDIR="$ITER_LOG/qemu_iter${iter}"; mkdir -p "$QDIR"
  [ -f /tmp/reharness_qemu_plat.txt ] && cp /tmp/reharness_qemu_plat.txt "$QDIR/qemu_serial.log"
  [ -f /tmp/edu_qemu_run.txt ] && cp /tmp/edu_qemu_run.txt "$QDIR/qemu_judge.txt"
  if [ $QRC -eq 0 ]; then echo "  ✓ QEMU 成功 (尝试 $iter)"; QEMU_OK=1; break; fi
  echo "  ✗ QEMU 失败 rc=$QRC, 喂 LLM 修复..."
  QEMU_ERR=$(grep -aE 'RIP:|Call Trace|Oops:|BUG:|probe.*failed|Kernel panic|dumped core' /tmp/reharness_qemu_plat.txt 2>/dev/null | head -20)
  OB=$(wc -c < /tmp/reharness_qemu_plat.txt 2>/dev/null)
  [ -z "$QEMU_ERR" ] && QEMU_ERR="(QEMU 输出 ${OB} 字节; 可能卡死/超时。检查 probe 是否阻塞/风暴)"
  echo "$QEMU_ERR" > "$QDIR/error.txt"
  cat > /tmp/edu_qemu_fix.txt <<FIXHEAD
你是 Linux 内核驱动开发专家(7.1.0-rc7)。合成驱动在 QEMU 运行时出错, 请修复。
## 运行时错误
$QEMU_ERR

$CONSTRAINTS
## 当前 $MODULE.c
FIXHEAD
  cat "$DRVDIR/$MODULE.c" >> /tmp/edu_qemu_fix.txt
  echo -e "\n## 要求\n只修运行时错误, 输出完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> /tmp/edu_qemu_fix.txt
  llm_write_c /tmp/edu_qemu_fix.txt || true
  save_iter qemu "$iter" /tmp/edu_qemu_fix.txt "$QDIR/error.txt"
  echo "  → 重编..."
  compile_once || echo "  重编失败"
done
if [ "$QEMU_OK" -eq 1 ]; then
  echo ""; echo "[5] trace 一致性 (.ris probe 模块 vs 实际 MMIO 访问)"
  if [ -f /tmp/reharness_qemu_plat.txt ] && [ -f "$BUNDLE/$BASE.ris" ] && [ -f "$BUNDLE/$BASE.dspec" ]; then
    python3 "$HERE/tools/trace_match.py" /tmp/reharness_qemu_plat.txt "$BUNDLE/$BASE.ris" "$BUNDLE/$BASE.dspec" > /tmp/trace_match.out 2>/tmp/trace_match.err
    TRC=$?
    cat /tmp/trace_match.err | sed 's/^/    /'
    cat /tmp/trace_match.out
    cp /tmp/trace_match.out "$ITER_LOG/trace_match.txt" 2>/dev/null
    if [ $TRC -eq 0 ]; then
      echo "############ $BASE 端到端成功 + trace 一致性通过 ############"
      exit 0
    else
      echo "############ $BASE probe 通过但 trace 一致性失败 (见 $ITER_LOG/trace_match.txt) ############"
      exit 4
    fi
  else
    echo "  (缺 trace_match 输入, 跳过)"; echo "############ $BASE 端到端成功 ############"; exit 0
  fi
fi
echo ""; echo "############ $BASE QEMU 迭代用尽 (见 $ITER_LOG/) ############"; exit 1
