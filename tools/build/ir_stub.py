#!/usr/bin/env python3
"""IR Stub: 重写 LLVM IR，把不透明的 declare 替换成有体的 stub。

让 SVF 能追踪通过内核 API 函数的数据流：
- ioremap 系列 → call malloc (新 MMIO base 对象)
- devm_kmalloc → call malloc(arg1) (新堆对象)
- readl/writel/misc_register 等 → noop (不影响别名分析)

已经 define internal 的函数 (pci_set_drvdata 等 static inline) 不需要 stub。
注意: LLVM IR 里 ; 是注释，不能用 ; 分隔指令，必须用换行。
"""
import re

_MALLOC_STUBS = {
    "pci_ioremap_bar":      ("ptr", "(ptr %0, i32 %1)", "call ptr @malloc(i64 4096)"),
    "devm_ioremap_resource":("ptr", "(ptr %0, ptr %1)", "call ptr @malloc(i64 4096)"),
    "ioremap":               ("ptr", "(i64 %0, i64 %1)", "call ptr @malloc(i64 %1)"),
    "ioremap_wc":            ("ptr", "(i64 %0, i64 %1)", "call ptr @malloc(i64 %1)"),
    "ioremap_uc":             ("ptr", "(i64 %0, i64 %1)", "call ptr @malloc(i64 %1)"),
    "ioremap_cache":         ("ptr", "(i64 %0, i64 %1)", "call ptr @malloc(i64 %1)"),
    "devm_ioremap":           ("ptr", "(ptr %0, i64 %1, i64 %2)", "call ptr @malloc(i64 %2)"),
    "devm_ioremap_wc":       ("ptr", "(ptr %0, i64 %1, i64 %2)", "call ptr @malloc(i64 %2)"),
    "devm_platform_ioremap_resource": ("ptr", "(ptr %0, i32 %1)", "call ptr @malloc(i64 4096)"),
    "devm_kmalloc":          ("ptr", "(ptr %0, i64 %1, i32 %2)", "call ptr @malloc(i64 %1)"),
    "devm_kzalloc":          ("ptr", "(ptr %0, i64 %1, i32 %2)", "call ptr @malloc(i64 %1)"),
    "pci_iomap":             ("ptr", "(ptr %0, i32 %1, i64 %2)", "call ptr @malloc(i64 4096)"),
    "devm_pci_iomap":        ("ptr", "(ptr %0, i32 %1, i64 %2)", "call ptr @malloc(i64 4096)"),
    "kzalloc":               ("ptr", "(i64 %0, i32 %1)", "call ptr @malloc(i64 %0)"),
    "kmalloc":               ("ptr", "(i64 %0, i32 %1)", "call ptr @malloc(i64 %0)"),
    "dma_alloc_coherent":    ("ptr", "(ptr %0, i64 %1, ptr %2, i32 %3)", "call ptr @malloc(i64 %1)"),
}

_NOOP_STUBS = {
    "pci_enable_device_mem":  ("i32", "(ptr %0)", "ret i32 0"),
    "pci_request_regions":   ("i32", "(ptr %0, ptr %1)", "ret i32 0"),
    "pci_disable_device":    ("void", "(ptr %0)", "ret void"),
    "pci_release_regions":   ("void", "(ptr %0)", "ret void"),
    "misc_register":         ("i32", "(ptr %0)", "ret i32 0"),
    "misc_deregister":       ("void", "(ptr %0)", "ret void"),
    "iounmap":               ("void", "(ptr %0)", "ret void"),
    "readl":                 ("i32", "(ptr %0)", "ret i32 0"),
    "writel":                ("void", "(i32 %0, ptr %1)", "ret void"),
    "readb":                 ("i8", "(ptr %0)", "ret i8 0"),
    "writeb":                ("void", "(i8 %0, ptr %1)", "ret void"),
    "readw":                 ("i16", "(ptr %0)", "ret i16 0"),
    "writew":                ("void", "(i16 %0, ptr %1)", "ret void"),
    "ioread32":              ("i32", "(ptr %0)", "ret i32 0"),
    "iowrite32":             ("void", "(i32 %0, ptr %1)", "ret void"),
    "ioread8":               ("i8", "(ptr %0)", "ret i8 0"),
    "iowrite8":             ("void", "(i8 %0, ptr %1)", "ret void"),
    "copy_to_user":          ("i64", "(ptr %0, ptr %1, i64 %2)", "ret i64 0"),
    "copy_from_user":        ("i64", "(ptr %0, ptr %1, i64 %2)", "ret i64 0"),
    "dev_err":               ("void", "(ptr %0, ptr %1, ...)", "ret void"),
    "dev_info":              ("void", "(ptr %0, ptr %1, ...)", "ret void"),
    "dev_warn":              ("void", "(ptr %0, ptr %1, ...)", "ret void"),
    "pr_err":                ("void", "(ptr %0, ...)", "ret void"),
    "pr_info":               ("void", "(ptr %0, ...)", "ret void"),
    "pr_warn":               ("void", "(ptr %0, ...)", "ret void"),
    "printk":                ("void", "(ptr %0, ...)", "ret void"),
    "__pci_register_driver":  ("i32", "(ptr %0, ptr %1)", "ret i32 0"),
    "platform_driver_register": ("i32", "(ptr %0)", "ret i32 0"),
    "platform_driver_unregister": ("void", "(ptr %0)", "ret void"),
    "request_irq":           ("i32", "(i32 %0, ptr %1, i32 %2, ptr %3, ptr %4, ptr %5)", "ret i32 0"),
    "free_irq":              ("void", "(i32 %0, ptr %1)", "ret void"),
    "kfree":                 ("void", "(ptr %0)", "ret void"),
    "dma_free_coherent":     ("void", "(ptr %0, i64 %1, ptr %2, i64 %3)", "ret void"),
    "dma_set_mask_and_coherent": ("i32", "(ptr %0, i64 %1)", "ret i32 0"),
    "spin_lock_init":        ("void", "(ptr %0)", "ret void"),
    "mutex_init":            ("void", "(ptr %0)", "ret void"),
}


def _build_all_stubs():
    """构建 {name: multi-line define body} dict."""
    stubs = {}
    for name, (ret, args, body) in _MALLOC_STUBS.items():
        stubs[name] = f"define {ret} @{name}{args} {{\n  %m = {body}\n  ret ptr %m\n}}"
    for name, (ret, args, body) in _NOOP_STUBS.items():
        if body.startswith("call "):
            stubs[name] = f"define {ret} @{name}{args} {{\n  %m = {body}\n  ret {ret} %m\n}}"
        else:
            stubs[name] = f"define {ret} @{name}{args} {{\n  {body}\n}}"
    return stubs

ALL_STUBS = _build_all_stubs()


def stub_ir(ll_text: str) -> str:
    """重写 LLVM IR text：把不透明的 declare 替换成有体的 stub。

    1. 删除需要 stub 的 declare 行
    2. 在 metadata 区之前插入 declare malloc + define stub (metadata 必须在文件末尾)
    3. 保留其他 declare (dbg 等)
    """
    lines = ll_text.split("\n")
    out_lines = []
    stubbed = []

    for line in lines:
        stripped = line.strip()
        m = re.match(r'^declare\s+.*@(\w+)\s*\(', stripped)
        if m:
            fname = m.group(1)
            if fname in ALL_STUBS:
                stubbed.append(fname)
                continue
        out_lines.append(line)

    # 找 metadata 区第一行 (! 开头)
    meta_start = len(out_lines)
    for i, line in enumerate(out_lines):
        if re.match(r'^!\w', line):
            meta_start = i
            break

    # 构造 stub 定义 (在 metadata 之前)
    stub_defs = [
        "; IR stub: kernel API models for SVF alias analysis",
        "declare ptr @malloc(i64)",
        "declare void @free(ptr)",
        "",
    ]
    for fname in stubbed:
        stub_defs.append(f"; stub: {fname}")
        stub_defs.append(ALL_STUBS[fname])
        stub_defs.append("")

    result = out_lines[:meta_start] + stub_defs + out_lines[meta_start:]
    return "\n".join(result)
