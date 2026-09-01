You are an expert Linux kernel module developer. Generate a complete, compilable Linux kernel module that reproduces the exact hardware access pattern described in the evidence package below (evidence JSON + RIS op block), including typed I2C/SPI message transactions and MMIO register accesses.

## CRITICAL: Module-to-Function Mapping

Every entry in evidence.modules MUST be generated as a separate C function. Do NOT skip, merge, or omit any module. The function name must match the module name exactly. Each function takes "struct driver_priv *priv" and uses "void __iomem *base = priv->base;" to access MMIO.

For each module's op list in the RIS block:
- `W(B4, ADDR) = value` -> writel(value, ADDR)
- `var := R(B4, ADDR)` -> variable = readl(ADDR)
- `IF guard { ... } ELSE { ... }` -> if (guard) { ...then... } else { ...else... }
- `LOOP <kind> ... (init=..; step=..; count=..; relation=..; bounded)` ->
  preserve `loop_kind`, `guard`, `init`, `step`, `count`, and `relation`
  when emitting the corresponding while/for/do loop with body; bounded
  post-decrement while guards must remain finite counter guards
- `RETURN value` -> return value

Where the address shows "base + REGISTER_NAME", use the register name as-is (it is a #define constant).
Every RIS address expression is a source-derived C expression. Preserve the
complete expression exactly, including the `Fixed.base` expression and dynamic terms
such as `priv->mmio + *off`; never lower a dynamic address to `base`,
`base + 0x0`, or another constant. The file-position or selector expression
must remain the address used by the generated access.
- `TXWRITE[transport] ...` -> regmap write. Use: regmap_write(regmap, SELECTOR, payload). Declare a static struct regmap *regmap at the top of the function if any TX ops appear. The target field is the regmap handle name.
- `TXUPDATE[transport] ... mask=.. value=..` -> regmap update. Use: regmap_update_bits(regmap, SELECTOR, mask, value).
- `TXREAD[transport] ...` with transport "regmap" -> regmap read. Use: regmap_read(regmap, SELECTOR, &var).
- `TXREAD[i2c] ... protocol i2c_transfer` -> preserve
  the target, message expression, and count exactly with
  `i2c_transfer(target, message, count)`.
- `TXREAD[spi] ... protocol beginning with "spi_sync"`
  -> preserve the target and message expression with `spi_sync(target, message)`
  or the exact locked variant named by the protocol.
- `var := STATE(field)` -> read the persistent field into the named variable.
- `STATE(field) := value` -> assign the value to the persistent field. For a field such as
  "dws->tx", use the corresponding generated private-state field (for example
  "priv->tx") and preserve the complete expression. These operations are part of the
  transfer state machine and must remain in source order with MMIO operations.
- `OUT(target) := value` -> write the value to the named output or buffer target.
- `var := VALUE(expr)` -> declare or assign the named local value before later
  operations use it. Preserve the RHS exactly; this is used for buffer reads such
  as `txw = *(u8 *)priv->tx` and must remain before any pointer movement.
- `DELAY(cycles)` -> preserve the timing operation using the appropriate Linux delay helper.
- For every "read", "write", or "rmw" operation, emit exactly one comment immediately
  before the lowered operation in this exact form, using the operation's supplied values:
  `/* REHARNESS_RIS_OP id=<op_id> kind=<Read|Write|ReadModifyWrite> status=lowered digest=<digest> */`
  Immediately after that receipt, emit the matching C AST anchor
  `__rh_op_<op_id>: { ... }` and put the lowered primitive(s) inside its direct
  compound statement. The receipt and label must use the same op_id. Do not omit,
  duplicate, or invent operation IDs, labels, or digests.
- For every `tx_read`, `tx_write`, or `tx_update` operation, emit exactly one
  transaction receipt immediately before its direct compound statement:
  `/* REHARNESS_TRANSACTION_OP id=<op_id> kind=<TransactionRead|TransactionWrite|TransactionUpdate> transport=<transport> status=lowered digest=<digest> */`.
  The `<digest>` is the evidence-supplied transaction digest. Do not use a
  different marker name such as `REHARNESS_RIS_TX`, and do not omit or invent
  a transaction marker.
For regmap operations, add #include <linux/regmap.h> and declare a dummy static struct regmap pointer for each unique target name. Since this is a harness, use NULL or a placeholder for the regmap pointer.

## Bus Type Detection

Check evidence.bus_type:
- If "pci": use pci_driver, pci_enable_device_mem, pci_request_regions, pci_ioremap_bar, pci_set_drvdata, module_pci_driver. Include <linux/pci.h>.
- If "platform" (default): use platform_driver, devm_platform_ioremap_resource, module_platform_driver. Include <linux/platform_device.h>.
- If target.qemu.registrar is present for a platform target, set the generated
  platform_driver's `.driver.name` to that exact manifest value. The registrar
  is the platform device identity and is not interchangeable with the source
  basename or module name.

## Required Components

1. Includes: <linux/module.h>, <linux/io.h>, <linux/fs.h>, <linux/uaccess.h>, <linux/miscdevice.h>, <linux/slab.h>, <linux/err.h>, <linux/of.h>, plus bus-specific headers.

2. Driver private struct containing (for the generic MMIO harness mode only):
   - void __iomem *base (the MMIO base address)
   - struct miscdevice misc (for user-space access)
   - struct device *dev

3. Trace instrumentation is runner-owned. The experiment compiler injects the
   canonical MMIO macros and function-entry events after synthesis. Do not
   emit `__rh_mmio_base`, `RH_SET_BASE`, `RH_TRACE_FN`, `rh_off`, or tracing
   read/write macro definitions yourself.

4. In generic MMIO harness mode (only when no public framework registration is
   present), provide file_operations with open, read, write:
   - open: store priv in file->private_data
   - read: use the file position (*ppos) as the MMIO offset. Read 4 bytes: val = readl(base + *ppos); copy_to_user(buf, &val, 4); *ppos += 4; return 4;
   - write: use the file position (*ppos) as the MMIO offset. Write 4 bytes: copy_from_user(&val, buf, 4); writel(val, base + *ppos); *ppos += 4; return 4;
   - Both read and write must check alignment: if (*ppos & 3) or count < 4, return -EINVAL.

5. Probe function:
   - devm_kzalloc for priv struct
   - PCI: pci_enable_device_mem, pci_request_regions, pci_ioremap_bar(pdev, 0)
   - Platform: devm_platform_ioremap_resource(pdev, 0)
   - RH_SET_BASE(base)
   - In generic MMIO harness mode, call every non-callback module function in
     evidence order, each preceded by RH_TRACE_FN("function_name"), then use
     misc_register with KBUILD_MODNAME.
   - If evidence.device_class or evidence.bind.callbacks describes a public
     Linux framework route, follow SUBSYSTEM CALLBACK WIRING instead. Do not
     add a misc-only substitute and do not call callback modules from probe.
   - Proper error handling

6. Remove function (return void for platform_driver): call the remove/suspend module functions if they exist, then misc_deregister.

7. PCI identity: If evidence.pci_identity exists with vendor/device, create pci_device_id table.

8. Module boilerplate: MODULE_LICENSE("GPL"), MODULE_DESCRIPTION, module_pci_driver or module_platform_driver.

## SUBSYSTEM CALLBACK WIRING

The evidence package is authoritative about Linux framework ownership. Use
evidence.device_class, evidence.bind.callbacks, and the source-derived facts
to reconstruct the framework object graph before emitting the probe. When
present, evidence.framework.callback_signatures is the authoritative C ABI
for each public callback field; copy its return type and parameter types
exactly, including pointer ownership and const qualifiers.

- Every `table.field = function` entry in `evidence.bind.callbacks` is a typed
  function-pointer binding. Define the named function with the exact callback
  signature in `evidence.framework.callback_signatures[table.field]`, assign it
  to the matching field on the matching framework object, and preserve the
  registration path that makes that object live. If a signature is absent,
  do not invent a framework callback; fail the candidate or use only the
  evidence-backed generic route.
- For a `file_operations.<field>` binding, emit one `struct file_operations`
  owner with that field assigned to the evidence function, assign the same
  owner to the registered character-device or misc-device object, and ensure
  the owner is reachable from the proven registration root. Preserve every
  bound field; do not replace a proven file-operations route with an unbound
  misc-only substitute.
- Do not call callback functions directly from probe, init, or a synthetic
  harness path. A callback is entered by the Linux subsystem after its owner
  object is registered; never call it with `NULL` or fabricated arguments.
- Do not infer a callback's context from its name or from a generic IRQ
  signature. The assigned field controls the signature. In particular,
  `gpio_irq_chip.parent_handler` is an `irq_flow_handler_t` and receives a
  `struct irq_desc *`; it is not an `irqreturn_t (*)(int, void *)` handler.
- For `gpio_irq_chip.parent_handler`, use the supplied `struct irq_desc *desc`
  with public accessors such as `irq_desc_get_handler_data(desc)` and
  `irq_desc_get_chip(desc)`. Do not treat `struct gpio_irq_chip` as a
  `struct irq_chip`, and do not reconstruct `desc` from an integer IRQ.
- `irq_set_handler_locked()` takes a `struct irq_data *`; pass the callback's
  existing `d` parameter directly. Never emit `irqd_to_irq(d)` or convert the
  callback context to an integer IRQ for this API.
- For `evidence.device_class == "gpio_controller"`, use the real gpiolib
  object graph: initialize the `gpio_chip` embedded in the private state,
  assign every mapped `gpio_chip.*` callback, attach the mapped `irq_chip`
  with `gpio_irq_chip_set_chip(girq, &ftgpio_irq_chip)` (using the exact
  evidence owner names), assign `gpio_irq_chip.parent_handler` with its typed
  signature, and register with `devm_gpiochip_add_data` (or the exact exported
  registration API proven by the evidence). If the evidence lists
  `gpio_generic_chip_init`, the target kernel prototype is
  `int gpio_generic_chip_init(struct gpio_generic_chip *chip, const struct
  gpio_generic_chip_config *cfg)`: pass the embedded generic chip first and
  the address of the complete config object second, for example
  `gpio_generic_chip_init(&priv->chip, &config)`. Do not reverse these
  arguments or pass `&priv->gc` as the config. Set `girq->num_parents`, allocate
  `girq->parents` with the device-managed allocator, reject allocation
  failure, and assign every parent IRQ obtained from the exact source resource
  acquisition call. For example, when `evidence.resources` says
  `acquisition: "platform_get_irq"`, call `platform_get_irq(pdev, index)`;
  do not substitute `platform_get_resource` or another resource API. If the
  evidence lists `gpio_generic_chip_init`, call that helper with the complete
  source-derived config before registration. Do not replace this with a
  misc-device-only wrapper and do not leave mapped GPIO callbacks or parent
  state as NULL.
- Do not add `.remove`, `.shutdown`, power-management callbacks, or other
  root fields unless the corresponding callback is present in
  `evidence.bind.callbacks` with an authoritative signature. Extra lifecycle
  code is not evidence-backed and may have a different ABI in the target
  kernel.
- Nested objects must be initialized before their registration sink. A
  callback assignment on an unregistered or unrelated object is not a valid
  lowering. Emit one owner object and one registration root for each proven
  framework route.
- Use only APIs exported by the target kernel headers. Do not use
  `irq_to_desc`, `no_llseek`, internal IRQ headers, or any other private
  implementation symbol to manufacture callback context. Use the callback's
  existing parameters and public accessors instead. Match the exact
  `platform_driver`/`pci_driver` field types from the target headers,
  including the current `.remove` return type.
- For IRQ callbacks receiving `struct irq_data *d`, pass `d` directly to
  `irq_set_handler_locked(d, ...)`; never emit `irqd_to_irq(d)` or any other
  conversion from the callback context to an integer IRQ.
- Include only headers named by evidence.bind.includes/evidence facts and
  headers required by the selected public subsystem. Do not invent a header
  because a type is unavailable; in particular, do not include
  `<linux/offsetof.h>` or define kernel structs/types already supplied by the
  target headers.
- Acquire each evidence resource in evidence.resources when it is required by
  the framework route, preserve its source-derived binding, and handle the
  listed evidence.framework.error_paths. The optional `required` and
  `failure_policy` fields are source-derived policy, not suggestions: for a
  `required:false` resource with `failure_policy:"probe_defer_only"`, preserve
  the source shape that returns only on `-EPROBE_DEFER` and continues with the
  resource error for other missing-resource cases. Do not replace a clock or
  IRQ resource with a `void *` placeholder when the callback path uses it.
- Never emit two definitions of the same function, driver object, private
  state, or instrumentation symbol. The probe must not contain calls to
  callback entries merely to make them appear reachable.

## REGISTER RECEIPT AND SOURCE ORDER RULES

- Lower every register operation in every `evidence.modules` entry exactly
  once, including operations in the probe, initialization, and framework
  registration function. Framework wiring does not authorize dropping probe
  hardware initialization. Preserve module/source order for the lowered
  operations.
- Each register operation has one global owner: the generated function whose
  name matches its `evidence.modules[].name`. Emit that operation's receipt and
  AST anchor only in the owner function. If probe, registration, or another
  callback calls the owner function, call it without a receipt or anchor and do
  not copy the owner's lowering into the caller. This uniqueness rule applies
  across all generated files and translation units.
- Emit a `REHARNESS_RIS_OP` receipt only for an evidence operation whose RIS
  form is `R(...)`, `W(...)`, or `RMW(...)`, copying that operation's `op_id`
  and `digest` from its op line. `STATE`, `VALUE`, `OUT`, and `DELAY` ops are
  semantic operations, not register receipts: preserve their semantics but do
  not invent register receipt IDs or digests for them.
- Never invent an operation ID, digest, register, callback, resource, or
  framework call. Use evidence.functions, evidence.resources, and
  evidence.framework.helper_calls/error_paths as the source-derived context
  for framework setup and error handling.

## Constants
If evidence.constants exist, define them as macros. These include register offset macros (e.g. DW_SPI_SSIENR = 0x08).

## Rules
- Use readl/writel for MMIO access (B4 width), readw/writew for B2 width.
- EVERY module in evidence.modules must become a separate function. No exceptions.
- The probe must lower all register operations in source order. In generic
  harness mode it may call non-callback modules for exercising; in a public
  Linux subsystem mode it must wire callback modules into their owner objects
  and must not call those callbacks from probe.
- Use register macro names directly (e.g. writel(0, base + DW_SPI_SSIENR)).
- Use devm_ managed resources where possible.
- Include error handling.
- Do NOT invent or skip register accesses. Every op in every module must appear.
- Preserve write VALUE expressions exactly as shown in the evidence. If the value contains
  pointer dereferences like *(u8 *)(priv->tx), generate them verbatim. If the value contains
  ternary expressions like (cond ? val1 : val2), use C ternary operators directly.
- The driver_priv struct MUST include ALL fields referenced by any module's operations
  (e.g. tx, rx, tx_len, rx_len, n_bytes, fifo_len, etc.). Add them with appropriate types
  (pointers as void *, counters as int/u32, flags as u32).
- Conditions in IF/LOOP ops reference priv fields (e.g. priv->rx_len). Do NOT replace them
  with local variables or constants.
- Preserve state_write operations for pointer movement and counters, including expressions
  such as dws->tx += dws->n_bytes and --dws->tx_len. Do not drop these as bookkeeping.
- Preserve value_bind and output_write operations in source order. A value_bind must
  use a stable local temporary, and output_write must occur before the corresponding
  receive-buffer pointer advance.
- Transaction (tx_*) operations represent typed bus accesses, not MMIO. Preserve
  their transport, protocol, target, selector, message, count, and source order;
  never convert an I2C/SPI message transaction into a fake MMIO register.

Driver name: __DRIVER_NAME__

Evidence JSON (device, registers, bind, functions, facts):
```json
__EVIDENCE__
```

RIS module operations — the authoritative op list. One module per function,
ops in source order. Each register/transaction op line carries `@op_id`,
`[reliability]`, `digest=...`, and the source location; copy digests and
op_ids verbatim into receipts:
```
__RIS__
```

Generate the complete C code in a single ```c code block.
