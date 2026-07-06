# reharness

libclang AST + 数据流/污点追踪的设备驱动寄存器交互序列（RIS）提取器。

driver-harness 用正则解析 C 驱动源码提取 RIS，README 自承应使用真正的 C 解析器。
reharness 用 **libclang AST + 过程间 call-graph 内联 + 流敏感数据流/污点追踪**重写提取器，
产出对齐 driver-harness `src/ir/formal.rs` 的 **`.ris` 形式化规约语言**（不产出任何 JSON）。

## 解决的正则方案四个硬伤

| 硬伤 | driver-harness (regex) | reharness |
|------|------------------------|-----------|
| 寄存器宏偏移 | 硬编码 virtio_map，其余驱动解析为 0 | libclang preprocessing record + 求值，任意 `#define REG 0x20` 均解析 |
| 过程间调用 | 包装函数内 MMIO 丢失 | call-graph + 包装函数内联（深度≤3） |
| 控制流/条件 | `condition` 恒为 None | `if/for/while` 分支谓词附到 op |
| 数据流 | 无法计算 `base+偏移`、无 RMW | 流敏感 store：`base+offset`、`ioremap`→BasePtr、readl→ReadTaint、RMW 检测 |

## 输出：`.ris` 形式化规约语言（唯一输出格式，无 JSON）

`extract` 产出单个 `.ris` 文本文件，文法：

```
driver gpio-ftgpio010 v0.1.0 {
  module ftgpio_gpio_set_config {
    val := R(B4, g->base.GPIO_DEBOUNCE_PRESCALE) -- Config
    IF (val == deb_div) {
      val := R(B4, g->base.GPIO_DEBOUNCE_EN) -- Config
      RMW(B4, g->base.GPIO_DEBOUNCE_EN) = val -- Config
    }
    W(B4, g->base.GPIO_DEBOUNCE_PRESCALE) = deb_div -- Config
  }
}
```

操作形式：
- `Read`：`var := R(width, addr) -- intent`
- `Write`：`W(width, addr) = expr -- intent`
- `ReadModifyWrite`：`RMW(width, addr) = transform -- intent`
- `Cond`：`IF guard { ... } ELSE { ... }`（按条件栈嵌套，路径不敏感）
- `Loop`：`LOOP count { ... }`
- `Delay`：`DELAY(cycles)`

形式化要素：
- **`Expr` 代数**：值/条件解析为 `Const | Var | BinOp{op,left,right} | Bits | Top`
  （`BIT(n)`→`Shl(1,n)`，`~x`→`BitXor(x, ⊤)`，`a | b`→`BitOr`）。
- **`RegAddr`**：解析出的寄存器宏 → `Symbolic{device, register}`（如 `g->base.GPIO_INT_EN`）；
  `base+offset` → `Fixed{base, offset}`；`base+变量` → `Computed(Expr)`。
- **`register_map`**：驱动**实际访问的寄存器**（从 ops 的 `reg_name` 收集，解析偏移），非内核头噪音。
- **`Cond` 嵌套**：同一分支谓词下的 op 嵌入 `IF guard { ... }`。

该规约对齐 driver-harness `src/ir/formal.rs`（`Expr`/`RISOp`/`FormalRIS`/性质 P1–P4），
可作为形式化验证、运行时 trace 比对、代码生成的输入。

## 提取器流水线

```
parse TU (libclang, 容错) → 宏偏移表 → 目标函数 →
  per-function 流敏感数据流 (store: var→AbsVal)
    ├ ioremap/devm_ioremap → BasePtr (污点源)
    ├ readl(addr) → 解析 RegAddr + ReadTaint
    ├ writel(val,addr) → 解析 + RMW 检测 (val 为同 addr 的 ReadTaint)
    ├ 分支内 op 附 condition
    └ 包装函数调用 → 内联其 ops
→ intent 标注 (基于解析后宏名) → 形式化为 .ris 规约
```

抽象值域（`extractor/taint.py`）：`BasePtr` / `Offset(base,off,reg_name)` / `ReadTaint(addr)` / `Const` / `SymExpr` / `Top`。

## 用法

```bash
./run.sh extract drivers/test/gpio-ftgpio010.c        # 提取 → output/ris.ris
./run.sh show output/ris.ris                           # 打印 .ris
./run.sh demo                                          # gpio-ftgpio010 → output/demo/gpio-ftgpio010.ris
./run.sh compare                                       # 全驱动提取统计
./run.sh test                                          # 测试套件
```

也可直接：`python3 -m extractor extract -s <src> -o <out.ris>`

## 依赖

- Python 3 + `clang.cindex`（随 libclang，路径 `/usr/lib/llvm-18/lib/libclang-18.so.18`）
- 无额外 Python 包依赖；无 Rust/JSON 依赖
- 测试可独立运行（`python3 tests/test_extractor.py`），也兼容 pytest

## 提取统计（17 个测试驱动，`./run.sh compare`）

```
TOTAL   461 ops / 129 寄存器解析 / 77 RMW / 62 分支条件 / 100 寄存器映射项
```

## 目录

```
extractor/        Python 提取器 (tu, macros, ast_model, mmio, taint, dataflow,
                  call_graph, intent, formal, formalize, extractor, cli)
tests/            pytest/独立测试
verification/     compare.py (全驱动提取统计)
drivers -> ../driver-harness/drivers
linux  -> ../driver-harness/linux
run.sh            调度器
```
