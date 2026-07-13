#!/usr/bin/env python3
"""reharness trace 一致性比对 + 覆盖率报告 (gpio/clk/generic, 偏移级)。
解析 QEMU 串口里的 [rh] R/W 0xOFF 行 → traced ops; 解析 .ris 的所有模块 + .dspec
寄存器偏移映射 → 每个模块的 expected ops; 对每个模块做子序列匹配 (expected ⊆ traced, 按序)。
用法: python3 tools/trace_match.py <serial_log> <ris_file> <dspec_file> [--exercised kw1,kw2]
输出: TRACE_MATCH_OK 或 TRACE_MATCH_FAIL:<缺失的模块/ops>
      + 覆盖率报告到 stderr"""
import re, sys

# ── 健壮的错误处理 ──
if len(sys.argv) < 4:
    print("用法: trace_match.py <serial_log> <ris_file> <dspec_file> [--exercised kw1,kw2]", file=sys.stderr)
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

# 5) 模块过滤: 默认检查所有非 IRQ 模块; --exercised 可限定子集
IRQ_KEYWORDS = ('irq', 'ack', 'mask', 'unmask', 'handler', 'interrupt')

exercised_keywords = None
if '--exercised' in sys.argv:
    idx = sys.argv.index('--exercised')
    if idx + 1 < len(sys.argv):
        exercised_keywords = [k.strip() for k in sys.argv[idx+1].split(',')]

def is_checkable(name):
    if any(kw in name.lower() for kw in IRQ_KEYWORDS):
        return False
    if exercised_keywords:
        return any(kw in name for kw in exercised_keywords)
    return True

# 分类所有模块
checkable_modules = {n: ops for n, ops in modules.items() if is_checkable(n)}
irq_modules = {n: ops for n, ops in modules.items() if not is_checkable(n)
               and any(kw in n.lower() for kw in IRQ_KEYWORDS)}
skipped_modules = {n: ops for n, ops in modules.items()
                   if not is_checkable(n) and n not in irq_modules}

# 边界处理
if not checkable_modules:
    print(f"[trace_match] 0 个可校验模块 (共 {len(modules)}), traced={len(traced)} ops — vacuous pass", file=sys.stderr)
    print("TRACE_MATCH_OK")
    sys.exit(0)

if not traced and checkable_modules:
    print(f"[trace_match] {len(checkable_modules)} 个可校验模块但 traced=0 ops — 可能 instrumentation 未生效", file=sys.stderr)
    print(f"TRACE_MATCH_FAIL: trace 为空 (检查 instrument_mmio 是否生效)")
    sys.exit(1)

# 匹配 + 收集覆盖率数据
failed = []
passed_modules = []
total_expected_ops = 0
total_matched_ops = 0
for name, expected in checkable_modules.items():
    total_expected_ops += len(expected)
    if subseq(expected, traced):
        passed_modules.append(name)
        # 计算匹配的 ops 数 (子序列匹配, 统计命中的)
        it = iter(traced)
        matched = 0
        for x in expected:
            for y in it:
                if x == y:
                    matched += 1
                    break
        total_matched_ops += matched
    else:
        it = iter(traced)
        missing = []
        for x in expected:
            found = False
            for y in it:
                if x == y:
                    found = True
                    break
            if not found:
                missing.append(x)
        total_matched_ops += (len(expected) - len(missing))
        failed.append(f"{name}: 缺失 {missing}")

# ── 覆盖率报告 ──
total_modules = len(modules)
checkable_count = len(checkable_modules)
passed_count = len(passed_modules)
irq_count = len(irq_modules)
traced_offsets = set(off for _, off in traced)
expected_offsets = set(off for ops in checkable_modules.values() for _, off in ops)
reg_map_count = len(reg_off)
covered_offsets = traced_offsets & expected_offsets

print(f"[trace_match] {checkable_count} 个可校验模块 (共 {total_modules}: "
      f"{passed_count} pass, {len(failed)} fail, {irq_count} IRQ skip, "
      f"{total_modules - checkable_count - irq_count} other skip), "
      f"traced={len(traced)} ops", file=sys.stderr)
for name, ops in checkable_modules.items():
    status = "✓" if subseq(ops, traced) else "✗"
    print(f"  {status} {name}: {len(ops)} ops {ops}", file=sys.stderr)

# 覆盖率汇总
print(f"", file=sys.stderr)
print(f"[coverage] 模块覆盖: {passed_count}/{checkable_count} 可校验模块通过 "
      f"({passed_count*100//checkable_count if checkable_count else 0}%); "
      f"{irq_count} IRQ 模块未行使; 共 {total_modules} 模块", file=sys.stderr)
print(f"[coverage] op 覆盖: {total_matched_ops}/{total_expected_ops} ops 命中 "
      f"({total_matched_ops*100//total_expected_ops if total_expected_ops else 0}%)", file=sys.stderr)
print(f"[coverage] 寄存器覆盖: {len(covered_offsets)}/{len(expected_offsets)} 寄存器偏移被访问 "
      f"({len(covered_offsets)*100//len(expected_offsets) if expected_offsets else 0}%)", file=sys.stderr)
print(f"[coverage] trace 级别: {'偏移级+exerciser' if exercised_keywords else '偏移级(probe-only)' if not traced else '偏移级'}", file=sys.stderr)

if not failed:
    print("TRACE_MATCH_OK")
    sys.exit(0)
else:
    print(f"TRACE_MATCH_FAIL: {'; '.join(failed)}")
    sys.exit(1)
