#!/bin/bash
# tools/e2e_common.sh — 公共 shell 逻辑 (被 run_e2e.sh source)
# 依赖调用方设置: HERE, DRVDIR, MODULE, KERNELDIR, INSTRUMENT(0|1)
set -u

# ── 临时文件隔离 (每个 run_e2e.sh 进程独立, 避免并行冲突) ──
RH_TMP="/tmp/rh_${$}"
mkdir -p "$RH_TMP"
trap 'rm -rf "$RH_TMP"' EXIT

# ── 预检: 在开始前验证所有依赖 ──
preflight() {
  local errors=0
  # KERNELDIR
  if [ ! -d "$KERNELDIR" ]; then
    echo "  ✗ KERNELDIR 不存在: $KERNELDIR"; errors=$((errors+1))
  elif [ ! -f "$KERNELDIR/Makefile" ]; then
    echo "  ✗ KERNELDIR 不是内核源码树 (无 Makefile): $KERNELDIR"; errors=$((errors+1))
  fi
  # bzImage
  local bz="${KERNEL_BZIMAGE:-$KERNELDIR/arch/x86/boot/bzImage}"
  if [ ! -f "$bz" ]; then
    echo "  ✗ bzImage 不存在: $bz"; errors=$((errors+1))
  fi
  # Pi SDK
  if ! command -v node >/dev/null 2>&1; then
    echo "  ✗ node 未安装 (Pi SDK 需要)"; errors=$((errors+1))
  fi
  if [ ! -f "$HERE/tools/pi/node_modules/@earendil-works/pi-coding-agent/package.json" ]; then
    echo "  ✗ Pi SDK 未安装 (cd tools/pi && npm install)"; errors=$((errors+1))
  fi
  # QEMU
  if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "  ✗ qemu-system-x86_64 未安装"; errors=$((errors+1))
  fi
  # libclang
  if ! python3 -c 'from extractor.tu import locate_libclang; raise SystemExit(0 if locate_libclang() else 1)' 2>/dev/null; then
    echo "  ✗ libclang 不可用"; errors=$((errors+1))
  fi
  # device-registrar (platform bus 需要)
  if [ "${BUS:-}" = "platform" ]; then
    local rdir="$HERE/verification/device-registrar"
    local rko="${REGISTRAR_KO:-$rdir/device-registrar.ko}"
    if [ ! -f "$rko" ] && [ -f "$rdir/Makefile" ]; then
      echo "  构建 device-registrar.ko ..."
      make -C "$rdir" KERNELDIR="$KERNELDIR" >/dev/null 2>&1 || true
    fi
    if [ ! -f "$rko" ]; then
      echo "  ✗ device-registrar.ko 不存在: $rko"; errors=$((errors+1))
    fi
  fi
  return $errors
}

# ── 候选后处理与原子接纳 ──
postprocess_candidate() {
  local candidate="$1"
  python3 "$HERE/tools/sanitize.py" "$candidate" || return 1
  if [ "${INSTRUMENT:-0}" = "1" ]; then
    python3 "$HERE/tools/instrument_mmio.py" "$candidate" || return 1
  fi
}

accept_existing_c() {
  local stage="${1:-existing}"
  local candidate="$DRVDIR/.${MODULE}.candidate.$$"
  local report="$RH_TMP/lowering_${stage}.json"
  cp "$DRVDIR/$MODULE.c" "$candidate" || return 1
  if ! postprocess_candidate "$candidate"; then
    rm -f "$candidate"
    return 1
  fi
  verify_lowering_candidate "$candidate" "$report"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    rm -f "$candidate"
    return "$rc"
  fi
  mv -f "$candidate" "$DRVDIR/$MODULE.c"
  mkdir -p "$ITER_LOG/lowering_${stage}"
  cp "$report" "$ITER_LOG/lowering_${stage}/report.json"
}

# ── LLM 合成: candidate → postprocess → lowering gate → atomic promote ──
llm_write_c() {
  local prompt_file="$1"
  local stage="${2:-repair}"
  local transport_max=2
  local semantic_max="${MAX_LOWERING_ITER:-3}"
  local semantic transport rc candidate report attempt_dir active_prompt
  candidate="$DRVDIR/.${MODULE}.candidate.$$"
  active_prompt="$prompt_file"
  for semantic in $(seq 1 "$semantic_max"); do
    for transport in $(seq 1 "$transport_max"); do
      timeout 600 bash "$HERE/tools/pi_synth.sh" < "$active_prompt" \
        > "$RH_TMP/fix_out.txt" 2>&1
      rc=$?
      if [ $rc -eq 0 ] && [ -s "$RH_TMP/fix_out.txt" ]; then
        break
      fi
      if [ "$transport" -lt "$transport_max" ]; then
        echo "  ⚠ Pi synth 失败 (rc=$rc), 传输重试 $((transport+1))/$transport_max..."
        sleep 2
      fi
    done
    if [ $rc -ne 0 ] || [ ! -s "$RH_TMP/fix_out.txt" ]; then
      echo "  ⚠ Pi synth 传输重试用尽 (rc=$rc)"
      rm -f "$candidate"
      return 1
    fi
    python3 - "$candidate" "$RH_TMP/fix_out.txt" <<'PY'
import re, sys
t = open(sys.argv[2]).read()
m = re.findall(r'```c\n(.*?)\n```', t, re.S)
code = m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code) < 50:
    print('  LLM 未返回有效代码'); sys.exit(1)
open(sys.argv[1], 'w').write(code + '\n')
print('  ✓ LLM 候选已提取')
PY
    if [ $? -ne 0 ] || ! postprocess_candidate "$candidate"; then
      rm -f "$candidate"
      return 1
    fi

    report="$RH_TMP/lowering_${stage}_${semantic}.json"
    attempt_dir="$ITER_LOG/lowering_${stage}_attempt${semantic}"
    mkdir -p "$attempt_dir"
    cp "$active_prompt" "$attempt_dir/prompt.txt"
    cp "$RH_TMP/fix_out.txt" "$attempt_dir/reply.txt"
    cp "$candidate" "$attempt_dir/${MODULE}.candidate.c"
    verify_lowering_candidate "$candidate" "$report"
    rc=$?
    if [ "$rc" -eq 0 ]; then
      cp "$report" "$attempt_dir/report.json"
      mv -f "$candidate" "$DRVDIR/$MODULE.c"
      echo "  ✓ LLM 候选通过 generation contract 并原子写回"
      return 0
    fi
    [ -f "$report" ] && cp "$report" "$attempt_dir/report.json"
    if [ "$rc" -ne 2 ]; then
      echo "  ✗ lowering verifier 基础设施失败"
      rm -f "$candidate"
      return "$rc"
    fi
    echo "  ✗ LLM 候选违反 generation contract ($semantic/$semantic_max)"
    cat > "$RH_TMP/lowering_retry_prompt.txt" <<RETRY
$(cat "$prompt_file")

## 上一个候选被 generation contract verifier 拒绝
$(cat "$report")

每个 register operation 必须在实现它的实际 MMIO 语句正前方恰好保留一次精确 receipt。不得只添加注释而不实现操作，也不得删除、复制、发明或中性化硬件副作用。

## 被拒绝的候选
$(cat "$candidate")

## 要求
输出完整修复版 $MODULE.c（一个 \`\`\`c 代码块）。
RETRY
    active_prompt="$RH_TMP/lowering_retry_prompt.txt"
  done
  rm -f "$candidate"
  return 2
}

# ── 单次编译: 成功返回 0 ──
compile_once() {
  (cd "$DRVDIR" && make clean >/dev/null 2>&1 && make KERNELDIR="$KERNELDIR" 2>&1) > "$RH_TMP/compile.log" 2>&1
  [ -f "$DRVDIR/$MODULE.ko" ]
}

# ── 保存迭代日志 ──
# save_iter <kind> <iter> <prompt_file> <error_file>
save_iter() {
  local kind="$1" n="$2" pf="$3" ef="$4"
  local d="$ITER_LOG/${kind}_iter${n}"
  mkdir -p "$d"
  [ -f "$pf" ] && cp "$pf" "$d/prompt.txt"
  [ -f "$ef" ] && cp "$ef" "$d/error.txt"
  [ -f "$RH_TMP/fix_out.txt" ] && cp "$RH_TMP/fix_out.txt" "$d/reply.txt"
  [ -f "$DRVDIR/$MODULE.c" ] && cp "$DRVDIR/$MODULE.c" "$d/${MODULE}.c"
}

# ── Makefile 生成 ──
gen_makefile() {
  cat > "$DRVDIR/Makefile" <<EOF
obj-m += $MODULE.o
KERNELDIR ?= $KERNELDIR
all:
	\$(MAKE) -C \$(KERNELDIR) M=\$(CURDIR) modules
clean:
	\$(MAKE) -C \$(KERNELDIR) M=\$(CURDIR) clean
EOF
}

# ── 编译迭代循环 ──
# 用法: compile_loop MAX_ITER CONSTRAINTS_VAR
compile_loop() {
  local max="$1" constraints="$2"
  local ok=0
  for iter in $(seq 1 "$max"); do
    echo "  --- 编译 $iter/$max ---"
    if ! verify_current_lowering "$RH_TMP/compile_pre${iter}_lowering.json"; then
      echo "  ✗ 当前代码未通过 generation contract，拒绝编译"
      return 1
    fi
    if compile_once; then
      if ! verify_current_lowering "$RH_TMP/compile_post${iter}_lowering.json"; then
        echo "  ✗ 编译后 generation contract 复核失败"
        return 1
      fi
      echo "  ✓ 编译成功 (尝试 $iter)"; ok=1; break
    fi
    echo "  ✗ 编译失败, 喂 LLM 修复..."
    grep -iE 'error:|warning:' "$RH_TMP/compile.log" | head -15 | sed 's/^/    /'
    if [ "$iter" -eq "$max" ]; then
      break
    fi
    grep -iE 'error:|warning:' "$RH_TMP/compile.log" | head -40 > "$RH_TMP/compile_err.txt"
    cat > "$RH_TMP/compile_fix.txt" <<FIXHEAD
你是 Linux 内核驱动开发专家(目标内核 ${KERNEL_RELEASE:-unknown})。下面的驱动编译失败, 请修复。
## 编译错误
$(grep -iE 'error:|warning:' "$RH_TMP/compile.log" | head -25)

$constraints
## 当前 $MODULE.c
FIXHEAD
    cat "$DRVDIR/$MODULE.c" >> "$RH_TMP/compile_fix.txt"
    echo -e "\n## 要求\n只输出修复后的完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> "$RH_TMP/compile_fix.txt"
    llm_write_c "$RH_TMP/compile_fix.txt" "compile_${iter}" || return 1
    save_iter compile "$iter" "$RH_TMP/compile_fix.txt" "$RH_TMP/compile_err.txt"
  done
  return $(( 1 - ok ))
}
