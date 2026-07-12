#!/usr/bin/env python3
"""reharness trace 一致性比对 (gpio, 偏移级)。
解析 QEMU 串口里的 [rh] R/W 0xOFF 行 → traced ops; 解析 .ris 的 probe 模块 + .dspec
寄存器偏移映射 → expected ops; 子序列匹配 (expected ⊆ traced, 按序)。
用法: python3 tools/trace_match.py <serial_log> <ris_file> <dspec_file>
输出: TRACE_MATCH_OK 或 TRACE_MATCH_FAIL:<缺失的 op>"""
import re, sys

log = open(sys.argv[1]).read()
ris = open(sys.argv[2]).read()
dspec = open(sys.argv[3]).read()

# 1) 寄存器名 → 偏移 (从 .dspec: "register NAME: B? at base + 0xOFF")
reg_off = {}
for m in re.finditer(r'register\s+(\w+):\s*B\d+\s+at\s+base\s+\+\s+(0x[0-9a-fA-F]+)', dspec):
    reg_off[m.group(1)] = int(m.group(2), 16)

# 2) .ris probe 模块 → expected ops (op, offset)
#    找 module <name>_probe { ... } (或 module ... probe ...)
expected = []
# 匹配 probe 模块: 名字含 probe
probe_blocks = re.findall(r'module\s+(\w*probe\w*)\s*\{(.*?)\n  \}', ris, re.S | re.I)
probe_body = None
for name, body in probe_blocks:
    probe_body = body; break
if not probe_body:
    # 退化: 取第一个 module
    m = re.search(r'module\s+\w+\s*\{(.*?)\n  \}', ris, re.S)
    probe_body = m.group(1) if m else ''

# 解析 ops: W(B?, expr.reg) = val ; R(B?, expr.reg) ; RMW(B?, expr.reg)
for line in probe_body.split('\n'):
    line = re.sub(r'--.*$', '', line).strip()
    if not line:
        continue
    # W(B4, g->base.GPIO_INT_EN) = 0x0   或  W(B4, [mmio]) = kbuf  (computed addr)
    m = re.match(r'(R|W|RMW)\(B\d+,\s*.*?\.(\w+)\)', line)
    if m:
        op, reg = m.group(1), m.group(2)
        off = reg_off.get(reg)
        if off is not None:
            # RMW 算作 R 然后 W
            if op == 'RMW':
                expected.append(('R', off)); expected.append(('W', off))
            else:
                expected.append((op, off))
            continue
    # computed addr: W(B4, [mmio]) / R(B4, [pl061->base]) — 偏移未知, 跳过
    # (probe 模块通常都是具名寄存器)

# 3) traced ops (从 [rh] R/W 0xOFF)
traced = []
for m in re.finditer(r'\[rh\]\s+(R|W)\s+0x([0-9a-fA-F]+)', log):
    traced.append((m.group(1), int(m.group(2), 16)))

# 4) 子序列匹配: expected 按序出现在 traced 中
def subseq(sub, seq):
    it = iter(seq)
    return all(x in it for x in sub)

ok = subseq(expected, traced)
print(f"[trace_match] expected={expected}", file=sys.stderr)
print(f"[trace_match] traced={traced[:30]}{'...' if len(traced)>30 else ''}", file=sys.stderr)
if ok:
    print("TRACE_MATCH_OK")
    sys.exit(0)
else:
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
    print(f"TRACE_MATCH_FAIL: 缺失 {missing} (expected={expected} traced={traced})")
    sys.exit(1)
