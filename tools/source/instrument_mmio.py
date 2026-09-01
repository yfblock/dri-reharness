#!/usr/bin/env python3
"""reharness MMIO trace instrumentation.
在合成驱动的 #include 之后注入 file-local 宏, 把 readl/writel/readb/writeb/readw/writew
包成记录 [rh] R/W 0xOFF 到 dmesg; 在 ioremap 赋值后注入 RH_SET_BASE(field) 记录基址。
同时给 file-local 函数注入 [rhfn] 入口事件，使 trace oracle 能把 MMIO 操作归属到
精确的运行时 callback，而不是依赖函数名子串或复用全局 trace。
假 MMIO 也会执行 writel 指令(CPU store), QEMU 丢弃但 printk 已发生 → trace 可捕获。
用法: python3 tools/instrument_mmio.py <driver.c>"""
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s
# Remove old instrumentation definitions before inserting one canonical block.
# Model output can contain a complete block, an incomplete block, or an orphan
# copy without the marker.  Removing definitions line-by-line handles all
# three forms without deleting surrounding driver code.
_OLD_INSTRUMENTATION_LINE = re.compile(
    r'^\s*(?:'
    r'/\* === reharness MMIO trace instrumentation.*\*/|'
    r'/\* === end instrumentation === \*/|'
    r'static void __iomem \*__rh_mmio_base;|'
    r'#(?:undef|define)\s+(?:RH_SET_BASE|RH_TRACE_FN|rh_off|'
    r'readl|writel|readb|writeb|readw|writew|ioread32|iowrite32)'
    r').*$'
)
s = "\n".join(
    line for line in s.splitlines()
    if not _OLD_INSTRUMENTATION_LINE.match(line)
)
s += "\n"
s = re.sub(r'\n\tRH_SET_BASE\([^)]*\);', '', s)
s = re.sub(r'\n\tRH_TRACE_FN\("[A-Za-z_]\w*"\);', '', s)

INSTR = r'''
/* === reharness MMIO trace instrumentation (file-local, after includes) === */
static void __iomem *__rh_mmio_base;
#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px\n", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s\n", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#undef readl
#define readl(p)    ({ u32 __v = __raw_readl(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writel
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })
#undef readb
#define readb(p)    ({ u8  __v = __raw_readb(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writeb
#define writeb(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writeb((v),(p)); })
#undef readw
#define readw(p)    ({ u16 __v = __raw_readw(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writew
#define writew(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writew((v),(p)); })
#undef ioread32
#define ioread32(p)    ({ u32 __v = __raw_readl(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef iowrite32
#define iowrite32(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })
/* === end instrumentation === */
'''

# 1) 在最后一个 #include 之后插入 instrumentation
matches = list(re.finditer(r'^[ \t]*#[ \t]*include[^\n]*\n', s, re.M))
if matches:
    pos = matches[-1].end()
    s = s[:pos] + INSTR + s[pos:]
else:
    s = INSTR + s

# 2) 在 ioremap 赋值后注入 RH_SET_BASE(field)
#    匹配: <field> = (各种 ioremap 变体)(...);
_IOREMAP_FUNCS = (
    'devm_ioremap_resource', 'pci_ioremap_bar', 'devm_ioremap',
    'ioremap', 'ioremap_wc', 'ioremap_uc', 'ioremap_cache',
    'devm_platform_ioremap_resource', 'devm_ioremap_wc',
    'pci_iomap', 'devm_pci_iomap',
)
_ioremap_pat = '|'.join(re.escape(f) for f in _IOREMAP_FUNCS)
def inj(m):
    field = m.group(1)
    return m.group(0) + '\n\tRH_SET_BASE(' + field + ');'
s = re.sub(rf'(\S+)\s*=\s*({_ioremap_pat})\([^;]*\);',
           inj, s, count=1)

# 3) 给 file-local 函数定义注入精确入口标记。参数列表允许跨行；通过要求
#    左花括号并排除分号/花括号，避免触碰 prototype 或宏。
#    只对函数体内含 MMIO 原语调用的函数注入：空段（如纯 remove/释放
#    函数）不应产生 [rhfn] 边界，否则 trace oracle 会把它们当作意外段。
_MMIO_CALL = re.compile(
    r'\b(?:readl|writel|readb|writeb|readw|writew|'
    r'ioread32|iowrite32)\s*\(')

def inject_function_entry(match):
    name = match.group(2)
    start = match.end() - 1  # 指向 '{'
    depth = 0
    for i in range(start, len(s)):
        if s[i] == '{':
            depth += 1
        elif s[i] == '}':
            depth -= 1
            if depth == 0:
                body = s[start:i]
                break
    else:
        body = ''
    if not _MMIO_CALL.search(body):
        return match.group(1)
    return match.group(1) + f'\n\tRH_TRACE_FN("{name}");'

s = re.sub(
    r'(^static\s+[^;{}]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{)',
    inject_function_entry, s, flags=re.M)

if s != orig:
    open(p, 'w').write(s)
    print(f"[instrument] 注入 MMIO trace 宏 + RH_SET_BASE + RH_TRACE_FN", file=sys.stderr)
else:
    print(f"[instrument] 未改动 (无 #include 或无 ioremap 赋值?)", file=sys.stderr)
