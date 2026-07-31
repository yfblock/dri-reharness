#!/bin/bash
# run_e2e.sh — 统一端到端: 提取 → Pi 合成 → 编译(迭代) → QEMU(迭代) → trace(迭代)
# 用法: ./run_e2e.sh <src.c> [subsystem|skip_synth] [skip_synth]
#   subsystem: gpio|clk|edu|generic|auto (从源码自动推断)
#   skip_synth=1: 跳过 Pi 合成, 用已有驱动
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
HERE="$ROOT"
cd "$ROOT"

KERNELDIR="${KERNELDIR:-$HERE/kernel/build}"
KERNEL_BZIMAGE="${KERNEL_BZIMAGE:-$KERNELDIR/arch/x86/boot/bzImage}"
KERNEL_RELEASE="${KERNEL_RELEASE:-$(make -s -C "$KERNELDIR" kernelrelease 2>/dev/null || echo unknown)}"
SRC="${1:?用法: $0 <src.c> [subsystem|skip_synth] [skip_synth]}"
SUBSYSTEM="${2:-auto}"
SKIP_SYNTH="${3:-0}"

# 兼容: 如果 $2 是 0/1, 当作 skip_synth
case "$SUBSYSTEM" in
  0|1) SKIP_SYNTH="$SUBSYSTEM"; SUBSYSTEM="auto" ;;
esac
BASE=$(basename "$SRC" .c)
MODULE=$(echo "$BASE" | tr - _)           # gpio-pl061 -> gpio_pl061
BUNDLE="output/$BASE"
DRVDIR="output/${MODULE}"

# ── 自动推断子系统 ──
detect_subsystem() {
  local src="$1"
  grep -qE 'gpio_chip|GPIOCHIP' "$src" 2>/dev/null && echo "gpio" && return
  grep -qE 'clk_hw|clk_ops|CLK_OF_DECLARE|struct clk' "$src" 2>/dev/null && echo "clk" && return
  grep -qE 'pci_driver|module_pci_driver|pci_register_driver' "$src" 2>/dev/null && echo "edu" && return
  echo "generic"
}
if [ "$SUBSYSTEM" = "auto" ]; then
  SUBSYSTEM=$(detect_subsystem "$SRC")
fi

# ── target profile (按子系统配置) ──
QEMU_DEVICE=""
REGISTRAR_TARGET=""
EXERCISER=""
EXERCISER_ARGS=""
PROBE_PATTERN="probed|registered"
TRACE_TYPE="offset"
INSTRUMENT=1
TRACE_EXERCISED=""  # 传给 trace_match --exercised

case "$SUBSYSTEM" in
  gpio)
    BUS="platform"
    REGISTRAR_TARGET="$MODULE"
    EXERCISER="test/gpio_trace_test"
    EXERCISER_ARGS="/dev/gpiochip0"
    PROBE_PATTERN="probed|registered|gpiochip"
    TRACE_TYPE="offset"
    TRACE_EXERCISED="probe,get_direction,direction_input,direction_output,get_value,set_value"
    ;;
  edu)
    BUS="pci"
    QEMU_DEVICE="edu"
    MODULE="${MODULE}_drv"
    DRVDIR="output/${MODULE}"
    EXERCISER="test/edu_trace_test"
    EXERCISER_ARGS="/dev/${MODULE}"
    PROBE_PATTERN="probed|edu device id|edu probed"
    TRACE_TYPE="value"
    INSTRUMENT=0
    ;;
  ahci)
    BUS="pci"
    QEMU_DEVICE="ahci"
    MODULE="${MODULE}_drv"
    DRVDIR="output/${MODULE}"
    PROBE_PATTERN="probed|registered|ahci|HOST_CTL"
    TRACE_TYPE="offset"
    INSTRUMENT=1
    ;;
  clk)
    BUS="platform"
    # probe-only: 无 exerciser, trace_match 只检查 probe 模块 init 写入
    PROBE_PATTERN="probed|registered|clk"
    TRACE_TYPE="offset"
    TRACE_EXERCISED="probe"
    ;;
  generic|*)
    BUS="platform"
    # probe-only
    TRACE_TYPE="offset"
    TRACE_EXERCISED="probe"
    ;;
esac

export KERNEL_BZIMAGE
ITER_LOG="$DRVDIR/iter_log"

# source 公共逻辑 (含 preflight + 隔离 tmp)
source "$HERE/tools/e2e_common.sh"

echo "############ reharness 端到端 ############"
echo "driver: $SRC  module: $MODULE  subsystem: $SUBSYSTEM  bus: $BUS  trace: $TRACE_TYPE"

# 0a. 预检依赖
echo ""; echo "[0a] 预检"
if preflight; then
  echo "  ✓ 依赖就绪"
else
  echo "  ✗ 依赖缺失, 退出"; exit 1
fi

# 0b. 基线 (非致命: flaky 测试不阻断 e2e)
echo ""; echo "[0b] reharness 自测"
./run.sh test >/dev/null 2>&1 && echo "  ✓ test passed" || echo "  ⚠ test 有失败 (继续, 不阻断 e2e)"

# 1. 提取 bundle
echo ""; echo "[1] 提取 bundle → $BUNDLE"
./run.sh bundle "$SRC" linux "$BUNDLE" 2>&1 | tail -1

# 清空 iter_log (e2e_common.sh 已 source, RH_TMP 已建)
rm -rf "$DRVDIR/iter_log"; mkdir -p "$DRVDIR/iter_log"

# 约束块 (subsystem-specific)
case "$SUBSYSTEM" in
  edu)
    CONSTRAINTS='## 关键约束 (不要破坏)
- PCI 驱动 0x1234:0x11e8 (QEMU edu 设备), 用 module_pci_driver
- file_operations.open 必须用 container_of(file->private_data, struct edu_priv, mdev) 取回 priv; struct miscdevice **没有** cdev 成员
- misc 设备名 = KBUILD_MODNAME, 节点在 /dev/'$MODULE'
- 保持 .ris 语义: readl/writel/copy_to/from_user
- **probe 禁止** DMA(request_irq/dma_alloc/writel DMA_CMD|DMA_IRQ) —— 触发 QEMU edu 中断风暴致 core dump; probe 只 ioremap+读id+misc_register'
    ;;
  gpio)
    CONSTRAINTS='## 关键约束 (不要破坏)
- platform_driver + gpio_chip, .driver.name = KBUILD_MODNAME (= "'"$MODULE"'"), module_platform_driver, MODULE_LICENSE("GPL")
- probe: devm_kzalloc, platform_get_resource(IORESOURCE_MEM,0), devm_ioremap_resource, 执行 .ris probe 的 init 写入, devm_gpiochip_add_data
- gpio_chip: gc.parent=&pdev->dev, gc.base=-1, gc.ngpio(默认8), gc.owner=THIS_MODULE; 回调按 .ris 模块实现
- MMIO 宽度按 .ris: B1=readb/writeb, B2=readw/writew, B4=readl/writel
- struct miscdevice 没有 cdev 成员; .set 在 7.1 返回 int; .remove 返回 void 字段 .remove
- **probe 禁止** request_irq / dma_alloc / 触发中断的写'
    ;;
  clk)
    CONSTRAINTS='## 关键约束 (不要破坏)
- platform_driver + clk_hw/clk_ops, .driver.name = KBUILD_MODNAME (= "'"$MODULE"'"), module_platform_driver, MODULE_LICENSE("GPL")
- probe: devm_kzalloc, platform_get_resource(IORESOURCE_MEM,0), devm_ioremap_resource, 执行 .ris probe 的 init 写入, devm_clk_hw_register
- clk_ops: 按 .ris 模块实现回调 (enable/disable/recalc_rate/set_rate/is_enabled/prepare/unprepare)
- MMIO 宽度按 .ris: B1=readb/writeb, B4=readl/writel
- .remove 返回 void; **probe 禁止** request_irq / dma_alloc'
    ;;
  generic|*)
    CONSTRAINTS='## 关键约束 (不要破坏)
- platform_driver, .driver.name = KBUILD_MODNAME (= "'"$MODULE"'"), module_platform_driver, MODULE_LICENSE("GPL")
- probe: devm_kzalloc, platform_get_resource(IORESOURCE_MEM,0), devm_ioremap_resource, 执行 .ris probe 的 init 写入
- MMIO 宽度按 .ris: B1=readb/writeb, B4=readl/writel
- .remove 返回 void; **probe 禁止** request_irq / dma_alloc'
    ;;
esac

# ── generation contract gate ──
# Every LLM-produced revision must account for the canonical Formal RIS before
# it is compiled or executed.  The current oracle proves receipt cardinality
# and digest identity; generated-C AST equivalence is a separate stronger gate.
verify_lowering_candidate() {
  local candidate="$1" report="$2"
  rm -f "$report"
  python3 "$HERE/verification/backend_lowering_oracle.py" \
    --formal "$BUNDLE/$BASE.formal.json" \
    --contract "$BUNDLE/generation-contract.json" \
    --generated "$candidate" \
    --output "$report" > "$RH_TMP/lowering_stdout.txt" 2>&1
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    return 0
  fi
  # A well-formed incomplete report is a candidate error (2).  Missing or
  # malformed output means the verifier/bundle itself failed (3).
  if python3 - "$report" <<'PY' >/dev/null 2>&1
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
assert report.get("complete") is False
assert not report.get("verifier_error")
PY
  then
    return 2
  fi
  cat "$RH_TMP/lowering_stdout.txt" >&2
  return 3
}

verify_current_lowering() {
  local report="${1:-$RH_TMP/lowering_current.json}"
  verify_lowering_candidate "$DRVDIR/$MODULE.c" "$report"
}

# 2. 合成
if [ "$SKIP_SYNTH" != "1" ]; then
  echo ""; echo "[2] Pi 合成 $MODULE.c"
  mkdir -p "$DRVDIR"
  # 合成 prompt (subsystem-specific)
  case "$SUBSYSTEM" in
    edu)
      cat > $RH_TMP/synth_prompt.txt <<PROMPT_HEAD
你是 Linux 内核驱动开发专家(目标内核 $KERNEL_RELEASE)。下面的 .ris/.dspec/.bind/.facts 由 reharness 从 QEMU edu PCI 驱动源码提取。请合成一个完整、可作为内核模块编译的 Linux PCI 驱动 $MODULE.c。
关键事实: PCI vendor 0x1234 device 0x11e8; 寄存器 IO_IRQ_STATUS=0x24 IO_IRQ_ACK=0x64 IO_DMA_SRC=0x80 IO_DMA_DST=0x88 IO_DMA_CNT=0x90 IO_DMA_CMD=0x98。
PROMPT_HEAD
      echo -e "\n## 要求\n1) pci_device_id(PCI_DEVICE(0x1234,0x11e8))/pci_driver/module_pci_driver/MODULE_LICENSE(\"GPL\")。\n2) probe: pci_enable_device_mem, pci_request_regions, pci_ioremap_bar(pdev,0), 读id(0x0), misc_register。\n3) irq_handler: 读IO_IRQ_STATUS写IO_IRQ_ACK。\n4) file_operations read/write: readl/writel + copy_to/from_user。\n5) probe 禁止 DMA/request_irq。6) 只输出一个 \`\`\`c 代码块。" >> $RH_TMP/synth_prompt.txt
      ;;
    gpio)
      cat > $RH_TMP/synth_prompt.txt <<PROMPT_HEAD
你是 Linux 内核驱动开发专家(目标内核 $KERNEL_RELEASE)。下面 .ris/.dspec/.bind/.facts 由 reharness 从真实上游 GPIO 驱动 $SRC 提取。请合成一个完整、可作为内核模块编译的 Linux platform GPIO 驱动 $MODULE.c (obj-m 名 $MODULE, KBUILD_MODNAME="$MODULE")。
PROMPT_HEAD
      echo -e "\n## 要求\n1) 把每个 .ris 模块映射到 gpio_chip 回调 (get_direction/direction_input/direction_output/get/set; probe→init写入)。\n2) 用 .ris 操作序列实现回调体, 偏移用 .dspec, 宽度按 B1/B2/B4。\n3) probe 结束 devm_gpiochip_add_data + dev_info。\n4) remove: void, devm 托管则基本为空。\n5) 只输出一个 \`\`\`c 代码块。" >> $RH_TMP/synth_prompt.txt
      ;;
    clk)
      cat > $RH_TMP/synth_prompt.txt <<PROMPT_HEAD
你是 Linux 内核驱动开发专家(目标内核 $KERNEL_RELEASE)。下面 .ris/.dspec/.bind/.facts 由 reharness 从真实上游 CLK 驱动 $SRC 提取。请合成一个完整、可作为内核模块编译的 Linux platform CLK 驱动 $MODULE.c (obj-m 名 $MODULE, KBUILD_MODNAME="$MODULE")。
PROMPT_HEAD
      echo -e "\n## 要求\n1) 把每个 .ris 模块映射到 clk_ops 回调 (enable/disable/recalc_rate/set_rate/is_enabled/prepare/unprepare; probe→init写入)。\n2) 用 .ris 操作序列实现回调体, 偏移用 .dspec, 宽度按 B1/B4。\n3) probe 结束 devm_clk_hw_register + dev_info。\n4) remove: void, devm 托管则基本为空。\n5) 只输出一个 \`\`\`c 代码块。" >> $RH_TMP/synth_prompt.txt
      ;;
    generic|*)
      cat > $RH_TMP/synth_prompt.txt <<PROMPT_HEAD
你是 Linux 内核驱动开发专家(目标内核 $KERNEL_RELEASE)。下面 .ris/.dspec/.bind/.facts 由 reharness 从真实上游驱动 $SRC 提取。请合成一个完整、可作为内核模块编译的 Linux platform 驱动 $MODULE.c (obj-m 名 $MODULE, KBUILD_MODNAME="$MODULE")。
PROMPT_HEAD
      echo -e "\n## 要求\n1) platform_driver, .driver.name = KBUILD_MODNAME, module_platform_driver, MODULE_LICENSE(\"GPL\")。\n2) probe: ioremap + 执行 .ris probe 模块的 init 写入序列 + dev_info。\n3) 用 .ris 操作序列实现回调体, 偏移用 .dspec, 宽度按 B1/B4。\n4) remove: void, devm 托管则基本为空。\n5) probe 禁止 DMA/request_irq。6) 只输出一个 \`\`\`c 代码块。" >> $RH_TMP/synth_prompt.txt
      ;;
  esac
  echo "## .ris" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/$BASE.ris" >> $RH_TMP/synth_prompt.txt
  echo -e "\n## .dspec (含寄存器偏移)" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/$BASE.dspec" >> $RH_TMP/synth_prompt.txt
  echo -e "\n## DeviceSpec JSON (机器可读函数/回调/root 证据)" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/$BASE.device-spec.json" >> $RH_TMP/synth_prompt.txt
  echo -e "\n## .bind (linux)" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/$BASE.linux.bind" >> $RH_TMP/synth_prompt.txt
  echo -e "\n## .facts (AST 类型、字段、回调、资源和错误路径)" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/$BASE.facts" >> $RH_TMP/synth_prompt.txt
  echo -e "\n## generation contract (机器可读；不得遗漏、复制或发明 RIS 操作)" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/generation-contract.json" >> $RH_TMP/synth_prompt.txt
  echo -e "\n## synthesis readiness / unresolved blockers" >> $RH_TMP/synth_prompt.txt; cat "$BUNDLE/score.txt" >> $RH_TMP/synth_prompt.txt
  echo -e "\n生成代码必须在实现每个 register operation 的实际 MMIO 语句正前方保留且仅保留一次：\n/* REHARNESS_RIS_OP id=<op_id> kind=<Read|Write|ReadModifyWrite> status=lowered digest=<16-hex-digest> */\n成功候选必须全部是 status=lowered；若任何项无法实现，本阶段应失败，不能用 rejected、中性值、删除操作或新增硬件副作用来伪装成功。" >> $RH_TMP/synth_prompt.txt
  echo -e "\n$CONSTRAINTS" >> $RH_TMP/synth_prompt.txt
  cp $RH_TMP/synth_prompt.txt "$ITER_LOG/synth/prompt.txt" 2>/dev/null || { mkdir -p "$ITER_LOG/synth"; cp $RH_TMP/synth_prompt.txt "$ITER_LOG/synth/prompt.txt"; }
  if ! llm_write_c "$RH_TMP/synth_prompt.txt" "synth"; then
    echo "  ✗ 合成候选未通过 generation contract"; exit 1
  fi
  cp "$RH_TMP/fix_out.txt" "$ITER_LOG/synth/reply.txt" 2>/dev/null
else
  echo "[2] 跳过合成 (用已有 $DRVDIR/$MODULE.c)"
  if ! accept_existing_c "skip_synth"; then
    echo "  ✗ 已有代码未通过 generation contract"; exit 1
  fi
fi

# 3. 编译 (迭代)
MAX_COMPILE_ITER="${MAX_COMPILE_ITER:-3}"
echo ""; echo "[3] 编译 (最多 $MAX_COMPILE_ITER 轮)"
gen_makefile
if compile_loop "$MAX_COMPILE_ITER" "$CONSTRAINTS"; then
  :
else
  echo "  ✗ 编译迭代用尽 (见 $ITER_LOG/)"; exit 1
fi

# 4. QEMU (迭代)
MAX_QEMU_ITER="${MAX_QEMU_ITER:-3}"
echo ""; echo "[4] QEMU (最多 $MAX_QEMU_ITER 轮)"
QEMU_OK=0
# 构建 qemu_run.sh 参数
QEMU_ARGS=("$MODULE" -b "$BUS" -t 90 -p "$PROBE_PATTERN")
[ -n "$QEMU_DEVICE" ] && QEMU_ARGS+=(-d "$QEMU_DEVICE")
[ -n "$REGISTRAR_TARGET" ] && QEMU_ARGS+=(-r "$REGISTRAR_TARGET")
[ -n "$EXERCISER" ] && QEMU_ARGS+=(-e "$EXERCISER" -a "$EXERCISER_ARGS")
for iter in $(seq 1 $MAX_QEMU_ITER); do
  echo "  --- QEMU $iter/$MAX_QEMU_ITER ---"
  bash qemu_run.sh "${QEMU_ARGS[@]}" > $RH_TMP/qemu_run.txt 2>&1
  QRC=$?
  tail -3 $RH_TMP/qemu_run.txt | sed 's/^/    /'
  QDIR="$ITER_LOG/qemu_iter${iter}"; mkdir -p "$QDIR"
  QEMU_LOG="/tmp/reharness_qemu_run.txt"
  [ -f "$QEMU_LOG" ] && cp "$QEMU_LOG" "$QDIR/qemu_serial.log"
  [ -f $RH_TMP/qemu_run.txt ] && cp $RH_TMP/qemu_run.txt "$QDIR/qemu_judge.txt"
  if [ $QRC -eq 0 ]; then
    if ! verify_current_lowering "$QDIR/lowering.json"; then
      echo "  ✗ QEMU 候选的 generation contract 复核失败"; exit 1
    fi
    echo "  ✓ QEMU 成功 (尝试 $iter)"
    QEMU_OK=1; LAST_QEMU_SERIAL="$QDIR/qemu_serial.log"; break
  fi
  echo "  ✗ QEMU 失败 rc=$QRC, 喂 LLM 修复..."
  QEMU_ERR=$(grep -aE 'RIP:|Call Trace|Oops:|BUG:|probe.*failed|Kernel panic|dumped core' "$QEMU_LOG" 2>/dev/null | head -20)
  OB=$(wc -c < "$QEMU_LOG" 2>/dev/null)
  [ -z "$QEMU_ERR" ] && QEMU_ERR="(QEMU 输出 ${OB} 字节; 可能卡死/超时)"
  echo "$QEMU_ERR" > "$QDIR/error.txt"
  cat > $RH_TMP/qemu_fix.txt <<FIXHEAD
你是 Linux 内核驱动开发专家(目标内核 $KERNEL_RELEASE)。合成驱动在 QEMU 运行时出错, 请修复。
## 运行时错误
$QEMU_ERR

$CONSTRAINTS
## 当前 $MODULE.c
FIXHEAD
  cat "$DRVDIR/$MODULE.c" >> $RH_TMP/qemu_fix.txt
  echo -e "\n## 要求\n只修运行时错误, 输出完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> $RH_TMP/qemu_fix.txt
  if ! llm_write_c "$RH_TMP/qemu_fix.txt" "qemu_${iter}"; then
    echo "  QEMU 修复候选未通过 generation contract"; exit 1
  fi
  save_iter qemu "$iter" $RH_TMP/qemu_fix.txt "$QDIR/error.txt"
  echo "  → 重编..."
  if ! compile_loop "$MAX_COMPILE_ITER" "$CONSTRAINTS"; then
    echo "  重编迭代用尽"; exit 1
  fi
done
if [ "$QEMU_OK" -ne 1 ]; then
  echo ""; echo "############ $BASE QEMU 迭代用尽 (见 $ITER_LOG/) ############"; exit 1
fi

# 5. trace 一致性 (迭代)
MAX_TRACE_ITER="${MAX_TRACE_ITER:-3}"
echo ""; echo "[5] trace 一致性 (最多 $MAX_TRACE_ITER 轮迭代)"
TRACE_OK=0
for titer in $(seq 1 $MAX_TRACE_ITER); do
  if [ "$TRACE_TYPE" = "value" ]; then
    # 值级 trace (edu): 已在 qemu_run.sh 里由 exerciser 校验 (EDU_TRACE_OK)
    # QEMU 步骤成功 = trace 通过
    if ! verify_current_lowering "$RH_TMP/final_value_trace_lowering.json"; then
      echo "  ✗ 最终 generation contract 复核失败"; exit 1
    fi
    echo "  ✓ trace (值级) 已在 QEMU 步骤通过"
    TRACE_OK=1; break
  fi
  # 偏移级 trace_match (用保存的 serial log, 不用 /tmp 实时文件避免被覆盖)
  QEMU_LOG="${LAST_QEMU_SERIAL:-/tmp/reharness_qemu_run.txt}"
  if [ ! -f "$QEMU_LOG" ] || [ ! -f "$BUNDLE/$BASE.ris" ] || [ ! -f "$BUNDLE/$BASE.dspec" ]; then
    echo "  (缺 trace_match 输入, 跳过)"; TRACE_OK=1; break
  fi
  TRACE_MATCH_ARGS=("$QEMU_LOG" "$BUNDLE/$BASE.ris" "$BUNDLE/$BASE.dspec")
  [ -n "$TRACE_EXERCISED" ] && TRACE_MATCH_ARGS+=(--exercised "$TRACE_EXERCISED")
  python3 "$HERE/tools/trace_match.py" "${TRACE_MATCH_ARGS[@]}" > $RH_TMP/trace_match.out 2>$RH_TMP/trace_match.err
  TRC=$?
  cat $RH_TMP/trace_match.err | sed 's/^/    /'
  cat $RH_TMP/trace_match.out
  TDIR="$ITER_LOG/trace_iter${titer}"; mkdir -p "$TDIR"
  cp $RH_TMP/trace_match.out "$TDIR/trace_match.txt" 2>/dev/null
  cp $RH_TMP/trace_match.err "$TDIR/trace_match.err" 2>/dev/null
  [ -f "$DRVDIR/$MODULE.c" ] && cp "$DRVDIR/$MODULE.c" "$TDIR/${MODULE}.c" 2>/dev/null
  if [ $TRC -eq 0 ]; then
    if ! verify_current_lowering "$TDIR/lowering.json"; then
      echo "  ✗ trace 候选的 generation contract 复核失败"; exit 1
    fi
    echo "  ✓ trace 一致性通过 (尝试 $titer)"; TRACE_OK=1; break
  fi
  echo "  ✗ trace 一致性失败 (尝试 $titer), 喂 LLM 修回调逻辑..."
  TRACE_FAIL=$(cat $RH_TMP/trace_match.out)
  cat > $RH_TMP/trace_fix.txt <<TFIX
你是 Linux 内核驱动开发专家(目标内核 $KERNEL_RELEASE)。合成驱动的 MMIO 访问 trace 与 .ris 规约不匹配, 请修复。
## trace 一致性失败
$TRACE_FAIL

## .ris (正确语义)
$(cat "$BUNDLE/$BASE.ris")

## .dspec (寄存器偏移)
$(cat "$BUNDLE/$BASE.dspec")

$CONSTRAINTS
## 当前 $MODULE.c
TFIX
  cat "$DRVDIR/$MODULE.c" >> $RH_TMP/trace_fix.txt
  echo -e "\n## 要求\n修复回调的 MMIO 访问使其匹配 .ris。输出完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> $RH_TMP/trace_fix.txt
  if ! llm_write_c "$RH_TMP/trace_fix.txt" "trace_${titer}"; then
    echo "  trace 修复候选未通过 generation contract"; exit 1
  fi
  save_iter trace "$titer" $RH_TMP/trace_fix.txt $RH_TMP/trace_match.out
  echo "  → 重编 + 重跑 QEMU..."
  if compile_loop "$MAX_COMPILE_ITER" "$CONSTRAINTS"; then
    bash qemu_run.sh "${QEMU_ARGS[@]}" > $RH_TMP/qemu_run.txt 2>&1
    QRC=$?
    QDIR2="$ITER_LOG/trace_qemu${titer}"; mkdir -p "$QDIR2"
    [ -f "$QEMU_LOG" ] && cp "$QEMU_LOG" "$QDIR2/qemu_serial.log"
    [ $QRC -ne 0 ] && echo "  QEMU 失败 rc=$QRC, 继续迭代"
  else
    echo "  重编失败, 继续迭代"
  fi
done
if [ "$TRACE_OK" -eq 1 ]; then
  if ! verify_current_lowering "$ITER_LOG/final-lowering.json"; then
    echo "  ✗ 最终 generation attestation 失败"; exit 1
  fi
  echo ""; echo "############ $BASE 端到端成功 + trace 一致性通过 ############"
  exit 0
else
  echo ""; echo "############ $BASE trace 一致性迭代用尽 (见 $ITER_LOG/) ############"
  exit 4
fi
