#!/usr/bin/env python3
"""确定性后处理: 删掉触发 QEMU edu 中断风暴的 DMA 启动写 (writel(...IO_DMA_CMD...)).
LLM 反复无视 'probe 禁 DMA' 约束; 这一行是风暴触发点, 删它即稳定, 其余 DMA 设置行无害。
用法: python3 tools/sanitize.py <edu_drv.c>"""
import re, sys
p = sys.argv[1]
s = open(p).read()
orig = s
# 删含 IO_DMA_CMD / DMA_CMD | DMA_IRQ 的 writel 行
s = re.sub(r'^[ \t]*writel\([^;]*IO_DMA_CMD[^;]*\);[ \t]*\n', '', s, flags=re.M)
s = re.sub(r'^[ \t]*writel\([^;]*DMA_CMD\s*\|\s*DMA_IRQ[^;]*\);[ \t]*\n', '', s, flags=re.M)
if s != orig:
    open(p, 'w').write(s)
    n = orig.count('\n') - s.count('\n')
    print(f"[sanitize] 删除 {n} 行 DMA 启动写 (IO_DMA_CMD) — 防止 QEMU 中断风暴", file=sys.stderr)
else:
    print("[sanitize] 无 DMA 启动写, 未改动", file=sys.stderr)
