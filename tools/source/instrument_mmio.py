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
# 去除旧 instrumentation (幂等): 删 INSTR 块 + RH_SET_BASE 行
s = re.sub(r'/\* === reharness MMIO trace instrumentation.*?=== end instrumentation === \*/\n*', '', s, flags=re.S)
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

# 3) 给生成的 file-local 函数注入精确入口标记。生成器稳定地产生单行函数签名，
#    后接单独一行的左花括号；仅处理定义，不触碰 prototype 或宏。
def inject_function_entry(match):
    name = match.group(2)
    return match.group(1) + f'\n\tRH_TRACE_FN("{name}");'

s = re.sub(
    r'(^static\s+[^\n;]+?\b([A-Za-z_]\w*)\s*\([^;\n]*\)\n\{)',
    inject_function_entry, s, flags=re.M)

if s != orig:
    open(p, 'w').write(s)
    print(f"[instrument] 注入 MMIO trace 宏 + RH_SET_BASE + RH_TRACE_FN", file=sys.stderr)
else:
    print(f"[instrument] 未改动 (无 #include 或无 ioremap 赋值?)", file=sys.stderr)
