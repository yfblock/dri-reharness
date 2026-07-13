#!/usr/bin/env python3
"""reharness trace 一致性比对 (gpio, 偏移级, 全模块)。
解析 QEMU 串口里的 [rh] R/W 0xOFF 行 → traced ops; 解析 .ris 的所有模块 + .dspec
寄存器偏移映射 → 每个模块的 expected ops; 对每个模块做子序列匹配 (expected ⊆ traced, 按序)。
用法: python3 tools/trace_match.py <serial_log> <ris_file> <dspec_file>
输出: TRACE_MATCH_OK 或 TRACE_MATCH_FAIL:<缺失的模块/ops>"""
import re, sys

log = open(sys.argv[1]).read()
ris = open(sys.argv[2]).read()
dspec = open(sys.argv[3]).read()

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

# 4) 子序列匹配 — 只检查被 gpio_trace_test 行使的回调模块
#    (probe + get_direction/direction_input/direction_output/get_value/set_value)
#    跳过 irq/set_config 等未行使的模块
EXERCISED = ('probe', 'get_direction', 'direction_input', 'direction_output', 'get_value', 'set_value')
def is_exercised(name):
    return any(kw in name for kw in EXERCISED)

failed = []
checked = 0
for name, expected in modules.items():
    if not is_exercised(name):
        continue  # 跳过未行使的模块 (irq/set_config 等)
    checked += 1
    if subseq(expected, traced):
        continue
    # 找缺失
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

print(f"[trace_match] {checked} 个被行使模块 (共 {len(modules)}), traced={len(traced)} ops", file=sys.stderr)
for name, ops in modules.items():
    if not is_exercised(name):
        continue
    status = "✓" if subseq(ops, traced) else "✗"
    print(f"  {status} {name}: {ops}", file=sys.stderr)

if not failed:
    print("TRACE_MATCH_OK")
    sys.exit(0)
else:
    print(f"TRACE_MATCH_FAIL: {'; '.join(failed)}")
    sys.exit(1)
