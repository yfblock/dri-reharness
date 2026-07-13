#!/bin/bash
# tools/e2e_common.sh — 公共 shell 逻辑 (被 run_e2e.sh source)
# 依赖调用方设置: HERE, DRVDIR, MODULE, KERNELDIR, INSTRUMENT(0|1)
set -u

# ── LLM 合成: 读 prompt 文件 → pi_synth.sh → 提取 C → sanitize + (可选 instrument) ──
llm_write_c() {
  local prompt_file="$1"
  timeout 600 bash "$HERE/tools/pi_synth.sh" < "$prompt_file" > /tmp/rh_fix_out.txt 2>&1
  python3 - "$DRVDIR/$MODULE.c" <<'PY'
import re, sys
t = open('/tmp/rh_fix_out.txt').read()
m = re.findall(r'```c\n(.*?)\n```', t, re.S)
code = m[0] if m else (t if ('#include' in t or 'static ' in t) else '')
if not code or len(code) < 50:
    print('  LLM 未返回有效代码'); sys.exit(1)
open(sys.argv[1], 'w').write(code + '\n')
print('  ✓ LLM 已写回')
PY
  python3 "$HERE/tools/sanitize.py" "$DRVDIR/$MODULE.c" || true
  if [ "${INSTRUMENT:-0}" = "1" ]; then
    python3 "$HERE/tools/instrument_mmio.py" "$DRVDIR/$MODULE.c" || true
  fi
}

# ── 单次编译: 成功返回 0 ──
compile_once() {
  (cd "$DRVDIR" && make clean >/dev/null 2>&1 && make KERNELDIR="$KERNELDIR" 2>&1) > /tmp/rh_compile.log 2>&1
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
  [ -f /tmp/rh_fix_out.txt ] && cp /tmp/rh_fix_out.txt "$d/reply.txt"
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
    grep -iE 'error:|warning:' /tmp/rh_compile.log | head -15 | sed 's/^/    /'
    grep -iE 'error:|warning:' /tmp/rh_compile.log | head -40 > /tmp/rh_compile_err.txt
    cat > /tmp/rh_compile_fix.txt <<FIXHEAD
你是 Linux 内核驱动开发专家(目标内核 7.1.0-rc7)。下面的驱动编译失败, 请修复。
## 编译错误
$(grep -iE 'error:|warning:' /tmp/rh_compile.log | head -25)

$constraints
## 当前 $MODULE.c
FIXHEAD
    cat "$DRVDIR/$MODULE.c" >> /tmp/rh_compile_fix.txt
    echo -e "\n## 要求\n只输出修复后的完整 $MODULE.c (一个 \`\`\`c 代码块)。" >> /tmp/rh_compile_fix.txt
    llm_write_c /tmp/rh_compile_fix.txt || true
    save_iter compile "$iter" /tmp/rh_compile_fix.txt /tmp/rh_compile_err.txt
  done
  return $(( 1 - ok ))
}
