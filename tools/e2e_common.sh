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
  if [ ! -f "$HERE/node_modules/@earendil-works/pi-coding-agent/package.json" ]; then
    echo "  ✗ Pi SDK 未安装 (npm install)"; errors=$((errors+1))
  fi
  # QEMU
  if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "  ✗ qemu-system-x86_64 未安装"; errors=$((errors+1))
  fi
  # libclang
  if [ ! -f /usr/lib/llvm-18/lib/libclang-18.so.18 ]; then
    echo "  ⚠ libclang-18 可能缺失 (提取会 fallback 到 regex)"; errors=$((errors+1))
  fi
  # device-registrar (platform bus 需要)
  if [ "${BUS:-}" = "platform" ]; then
    local rko="${REGISTRAR_KO:-/home/yfblock/Code/linux-driver-harness/test/device-registrar.ko}"
    if [ ! -f "$rko" ]; then
      echo "  ✗ device-registrar.ko 不存在: $rko"; errors=$((errors+1))
    fi
  fi
  return $errors
}

# ── LLM 合成: 读 prompt → pi_synth.sh (带重试) → 提取 C → sanitize + (可选 instrument) ──
llm_write_c() {
  local prompt_file="$1"
  local max_retries=2
  local attempt
  for attempt in $(seq 1 $max_retries); do
    timeout 600 bash "$HERE/tools/pi_synth.sh" < "$prompt_file" > "$RH_TMP/fix_out.txt" 2>&1
    local rc=$?
    if [ $rc -eq 0 ] && [ -s "$RH_TMP/fix_out.txt" ]; then
      break
    fi
    if [ $attempt -lt $max_retries ]; then
      echo "  ⚠ Pi synth 失败 (rc=$rc), 重试 $((attempt+1))/$max_retries..."
      sleep 2
    else
      echo "  ⚠ Pi synth 重试用尽 (rc=$rc)"
    fi
  done
  python3 - "$DRVDIR/$MODULE.c" "$RH_TMP/fix_out.txt" <<'PY'
import re, sys
t = open(sys.argv[2]).read()
m = re.findall(r'```c\n(.*?)\n```', t, re.S)
code = m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code) < 50:
    print('  LLM 未返回有效代码'); sys.exit(1)
open(sys.argv[1], 'w').write(code + '\n')
print('  ✓ LLM 已写回')
PY
  if [ $? -ne 0 ]; then return 1; fi
  python3 "$HERE/tools/sanitize.py" "$DRVDIR/$MODULE.c" || true
  if [ "${INSTRUMENT:-0}" = "1" ]; then
    python3 "$HERE/tools/instrument_mmio.py" "$DRVDIR/$MODULE.c" || true
  fi
  return 0
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
	\$(MAKE) -C \$(KERNELDIR) M=\$(PWD) modules
clean:
	\$(MAKE) -C \$(KERNELDIR) M=\$(PWD) clean
EOF
}

# ── 编译迭代循环 ──
# 用法: compile_loop MAX_ITER CONSTRAINTS_VAR
compile_loop() {
  local max="$1" constraints="$2"
  local ok=0
  for iter in $(seq 1 "$max"); do
    echo "  --- 编译 $iter/$max ---"
    if compile_once; then echo "  ✓ 编译成功 (尝试 $iter)"; ok=1; break; fi
    echo "  ✗ 编译失败, 喂 LLM 修复..."
    grep -iE 'error:|warning:' "$RH_TMP/compile.log" | head -15 | sed 's/^/    /'
    grep -iE 'error:|warning:' "$RH_TMP/compile.log" | head -40 > "$RH_TMP/compile_err.txt"
    cat > "$RH_TMP/compile_fix.txt" <<FIXHEAD
你是 Linux 内核驱动开发专家(目标内核 7.1.0-rc7)。下面的驱动编译失败, 请修复。
## 编译错误
$(grep -iE 'error:|warning:' "$RH_TMP/compile.log" | head -25)

$constraints
## 当前 $MODULE.c
FIXHEAD
    cat "$DRVDIR/$MODULE.c" >> "$RH_TMP/compile_fix.txt"
    echo -e "\n## 要求\n只输出修复后的完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> "$RH_TMP/compile_fix.txt"
    llm_write_c "$RH_TMP/compile_fix.txt" || true
    save_iter compile "$iter" "$RH_TMP/compile_fix.txt" "$RH_TMP/compile_err.txt"
  done
  return $(( 1 - ok ))
}
