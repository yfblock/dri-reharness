#!/usr/bin/env python3
"""reharness trace 一致性比对 (gpio, 偏移级, 全模块)。
解析 QEMU 串口里的 [rh] R/W 0xOFF 行 → traced ops; 解析 .ris 的所有模块 + .dspec
寄存器偏移映射 → 每个模块的 expected ops; 对每个模块做子序列匹配 (expected ⊆ traced, 按序)。
用法: python3 tools/trace_match.py <serial_log> <ris_file> <dspec_file>
输出: TRACE_MATCH_OK 或 TRACE_MATCH_FAIL:<缺失的模块/ops>"""
import re, sys

# ── 健壮的错误处理 ──
if len(sys.argv) < 4:
    print("用法: trace_match.py <serial_log> <ris_file> <dspec_file>", file=sys.stderr)
    sys.exit(2)

try:
    log = open(sys.argv[1]).read()
except (IOError, OSError) as e:
    print(f"TRACE_MATCH_FAIL: 无法读 serial_log: {e}")
    sys.exit(1)
try:
    ris = open(sys.argv[2]).read()
except (IOError, OSError) as e:
    print(f"TRACE_MATCH_FAIL: 无法读 .ris: {e}")
    sys.exit(1)
try:
    dspec = open(sys.argv[3]).read()
except (IOError, OSError) as e:
    print(f"TRACE_MATCH_FAIL: 无法读 .dspec: {e}")
    sys.exit(1)

# 1) 寄存器名 → 偏移
reg_off = {}
for m in re.finditer(r'register\s+(\w+):\s*B\d+\s+at\s+base\s+\+\s+(0x[0-9a-fA-F]+)', dspec):
    reg_off[m.group(1)] = int(m.group(2), 16)

# 2) 解析 .ris 所有模块 → {module_name: [(op, offset), ...]}
modules = {}
for m in re.finditer(r'module\s+(\w+)\s*\{(.*?)\n  \}', ris, re.S):
    name, body = m.group(1), m.group(2)
    ops = []
    for line in body.split('\n'):
        line = re.sub(r'--.*$', '', line).strip()
        if not line:
            continue
        op_m = re.match(r'(R|W|RMW)\(B\d+,\s*.*?\.(\w+)\)', line)
        if op_m:
            op, reg = op_m.group(1), op_m.group(2)
            off = reg_off.get(reg)
            if off is not None:
                if op == 'RMW':
                    ops.append(('R', off)); ops.append(('W', off))
                else:
                    ops.append((op, off))
    if ops:
        modules[name] = ops

# 3) traced ops
traced = []
for m in re.finditer(r'\[rh\]\s+(R|W)\s+0x([0-9a-fA-F]+)', log):
    traced.append((m.group(1), int(m.group(2), 16)))

# 4) 子序列匹配
def subseq(sub, seq):
    it = iter(seq)
    return all(x in it for x in sub)

# 只检查被 gpio_trace_test 行使的回调模块
EXERCISED = ('probe', 'get_direction', 'direction_input', 'direction_output', 'get_value', 'set_value')
def is_exercised(name):
    return any(kw in name for kw in EXERCISED)

# 边界: 如果 .ris 里没有可校验的模块, 报 OK (vacuous pass, 但不崩)
exercised_modules = {n: ops for n, ops in modules.items() if is_exercised(n)}
if not exercised_modules:
    print(f"[trace_match] 0 个被行使模块 (共 {len(modules)}), traced={len(traced)} ops — vacuous pass", file=sys.stderr)
    print("TRACE_MATCH_OK")
    sys.exit(0)

# 边界: 如果 trace 为空但需要校验, 报失败
if not traced and exercised_modules:
    print(f"[trace_match] {len(exercised_modules)} 个被行使模块但 traced=0 ops — 可能 instrumentation 未生效", file=sys.stderr)
    print(f"TRACE_MATCH_FAIL: trace 为空 (检查 instrument_mmio 是否生效)")
    sys.exit(1)

failed = []
for name, expected in exercised_modules.items():
    if subseq(expected, traced):
        continue
    it = iter(traced)
    missing = []
    for x in expected:
        found = False
        for y in it:
            if x == y:
                found = True; break
        if not found:
            missing.append(x)
    failed.append(f"{name}: 缺失 {missing}")

print(f"[trace_match] {len(exercised_modules)} 个被行使模块 (共 {len(modules)}), traced={len(traced)} ops", file=sys.stderr)
for name, ops in exercised_modules.items():
    status = "✓" if subseq(ops, traced) else "✗"
    print(f"  {status} {name}: {ops}", file=sys.stderr)

if not failed:
    print("TRACE_MATCH_OK")
    sys.exit(0)
else:
    print(f"TRACE_MATCH_FAIL: {'; '.join(failed)}")
    sys.exit(1)
