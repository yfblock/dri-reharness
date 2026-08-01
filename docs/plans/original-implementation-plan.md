# Plan: RIS + Function Spec to Generic Driver Generation

## Goal

Build a pipeline that extracts function-level register interaction sequences
(RIS), enriches them with function-level semantics, and composes them into a
backend-independent driver specification that can generate drivers for multiple
runtimes, not only Linux.

The intended architecture is:

```text
C driver
  -> RIS extraction
  -> FunctionSpec inference
  -> DeviceSpec composition
  -> backend-independent Driver IR
  -> backend codegen: Linux / RTOS / bare-metal / userspace harness
```

RIS is the register-programming layer. It is not the full driver spec by
itself.

## Formal Spec Language Direction

Use a formal, parseable specification language for device and function
semantics. The human-facing syntax may be DSL-like, but it must lower into a
strict core IR with a defined type system and semantics.

Artifact roles:

```text
.ris
  Register interaction sequence. Describes read/write/RMW/control-flow over
  registers.

.dspec
  Backend-independent device and function semantics. Describes what the device
  means: state, resources, registers, function roles, effects, contracts, and
  composition.

.bind
  Backend-specific binding. Describes how abstract dspec concepts map to a
  concrete runtime or API, such as Linux, RTOS, bare-metal C, or userspace
  harnesses.

.facts
  Source-derived facts that are useful for LLM-assisted synthesis but should
  not pollute the formal device semantics: structs, includes, constants,
  callback tables, resource acquisition snippets, error paths, and subsystem
  idioms.
```

The relationship is:

```text
RIS   = how registers are accessed
dspec = what those accesses mean at device/function level
bind  = how the abstract meaning is expressed in a concrete backend
facts = source facts and subsystem context for LLM-assisted reconstruction
```

Important implementation rule:

- The artifact boundary is logical, not a requirement to create one source file
  per artifact. Prefer fewer implementation modules with clear internal
  sections over many thin files.
- Split a module only when it has an independently testable responsibility, a
  different dependency profile, or multiple callers that would otherwise depend
  on unrelated code.
- Do not add parser/generator/helper files just because a new artifact exists.
  Start consolidated, then split when complexity proves the boundary is real.

Recommended implementation ownership:

```text
extractor/spec.py
  Owns the formal core data model and parse/emit helpers for dspec, bind, and
  facts while the grammar is still small.

extractor/spec_infer.py
  Owns semantic inference from RIS and source-derived facts, including callback
  table recognition, role inference, state binding, and source facts extraction.

extractor/metrics.py
  Owns extraction metrics and generation readiness scoring.

generator/common.py
  Owns shared codegen IR lowering, expression rendering, diagnostics, and
  scaffold helpers.

generator/harness.py
  Owns userspace harness generation.

generator/baremetal.py
  Owns portable bare-metal C generation.

generator/linux.py
  Added only after dspec/bind semantics are stable enough to justify a Linux
  backend.

synthesis.py
  Later optional module for LLM bundle construction, verification feedback
  normalization, and repair-loop orchestration. Split into a package only if the
  loop becomes large.
```

Core formal model:

```text
DeviceSpec =
  (State, Resources, Registers, Functions, Bindings, Invariants)

FunctionSpec =
  (Signature, Role, Context, Requires, Ensures, Effects, RISRef)

Effect =
  RegEffect | StateEffect | ResourceEffect | EventEffect

RIS =
  Read | Write | ReadModifyWrite | Cond | Loop | Delay | Seq
```

Function correctness should support Hoare-style reasoning:

```text
{ requires } RIS { ensures }
```

Example:

```text
function ack_irq(irq: LogicalIRQ) -> void {
  role interrupt_ack
  context irq_atomic

  bind dev: DeviceState from irq.owner
  bind base: MmioBase from dev.base
  bind line: UInt from irq.line

  require line < dev.num_irqs

  ris ftgpio_gpio_ack_irq {
    W(B4, base.GPIO_INT_CLR) = (1 << line)
  }

  effect clears_interrupt(line)
  ensure interrupt_pending[line] == false
}
```

The `.bind` file maps this backend-independent function to a runtime:

```text
backend linux {
  callback irq_chip.irq_ack = ack_irq

  map LogicalIRQ -> "struct irq_data *"
  map irq.line -> "irqd_to_hwirq(d)"
  map irq.owner -> "gpiochip_get_data(irq_data_get_irq_chip_data(d))"

  map MmioRead(B4) -> "readl"
  map MmioWrite(B4) -> "writel"
  map dev.base -> "g->base"
}
```

Another backend can reuse the same `.dspec`:

```text
backend baremetal {
  export ack_irq as "ftgpio_ack_irq"

  map LogicalIRQ -> "unsigned int line"
  map irq.line -> "line"
  map irq.owner -> "dev"

  map MmioRead(B4) -> "mmio_read32"
  map MmioWrite(B4) -> "mmio_write32"
  map dev.base -> "dev->base"
}
```

Design rule:

- `.dspec` must not depend on Linux-specific types such as `struct irq_data`.
- `.bind` may depend on backend APIs and naming conventions.
- Deterministic code generators consume `(RIS, dspec, bind)`, not RIS alone.
- LLM-assisted generators consume `(RIS, dspec, bind, facts, scaffold,
  verification feedback)`.

## Milestone 1: Stabilize RIS as the Register-Programming IR

Deliverables:

- Keep `.ris` as the canonical representation of register access behavior.
- Preserve precise module boundaries for callbacks, helpers, and framework
  entry points.
- Improve address modeling:
  - `Symbolic`: known base plus known register macro.
  - `Fixed`: literal MMIO address or offset when no register macro exists.
  - `Computed`: dynamic address expression such as config-space or indexed
    register access.
- Preserve expressions for values and guards without degrading to `Top` unless
  unavoidable.
- Add extraction quality metrics per module:
  - total ops
  - symbolic/fixed/computed address counts
  - unknown value count
  - condition/loop count
  - clang diagnostic count

Acceptance:

- Existing `drivers/test/*.c` and `drivers/virtio_mmio/virtio_mmio.c` pass the
  current test suite.
- Real Linux samples such as `gpio-ftgpio010`, `gpio-pl061`, `gpio-cadence`,
  and `virtio_mmio` produce stable RIS summaries.
- CLI stats match emitted RIS, not raw pre-dedup extraction.

## Milestone 2: Define Formal FunctionSpec in `.dspec`

Create a backend-independent formal schema for one driver function.

Proposed `.dspec` shape:

```text
function ftgpio_gpio_ack_irq(irq: LogicalIRQ) -> void {
  role interrupt_ack
  source "drivers/gpio/gpio-ftgpio010.c":56

  context irq_atomic
  locking inherited

  bind dev: DeviceState from irq.owner
  bind base: MmioBase from dev.base
  bind line: UInt from irq.line

  require line < dev.num_irqs

  ris ftgpio_gpio_ack_irq

  effect clears_interrupt(line)
  effect writes_register(GPIO_INT_CLR)

  ensure interrupt_pending[line] == false
}
```

Required concepts:

- `role`: `probe`, `remove`, `reset`, `init`, `suspend`, `resume`,
  `interrupt_ack`, `interrupt_mask`, `interrupt_unmask`, `read_config`,
  `write_config`, `setup_queue`, `notify`, `get_status`, `set_status`.
- `context`: normal thread, IRQ, atomic, sleepable, boot/init.
- `bind`: how source-level or abstract values map to device state.
- `effect`: abstract side effects beyond raw register writes.
- `require` / `ensure`: preconditions and postconditions.
- `ris`: link to the extracted RIS module.
- Types: `DeviceState`, `MmioBase`, `LogicalIRQ`, `UInt`, `Bool`,
  `Register`, `Clock`, `DmaRegion`, `Queue`, `Status`.

Acceptance:

- Generate FunctionSpec for `gpio-ftgpio010` callbacks:
  - `ack_irq`
  - `mask_irq`
  - `unmask_irq`
  - `set_irq_type`
  - `irq_handler`
  - `probe`
- Generate FunctionSpec for simplified and real `virtio_mmio` functions:
  - status functions
  - feature negotiation
  - queue setup
  - notify
  - interrupt handler

## Milestone 3: Infer Function Semantics

Implement inference passes that enrich RIS modules into FunctionSpec.

Inference sources:

- Function name and callback table binding.
- Parameter types and return type.
- Framework registration tables:
  - Linux: `platform_driver`, `irq_chip`, `gpio_chip`,
    `virtio_config_ops`, `dev_pm_ops`.
- Dataflow from source variables to state:
  - `g->base`
  - `dev->base`
  - `vm_dev->base`
  - `irq_data -> gpio_chip -> device state`
- Error returns:
  - `-ENOMEM`
  - `-ENODEV`
  - `PTR_ERR`
  - direct propagation from helper return values.

Initial heuristics:

- Callback table field determines semantic role more reliably than function
  name.
- A function with MMIO writes to interrupt clear/status registers and callback
  binding `.irq_ack` becomes `interrupt_ack`.
- A function with writes to status reset registers becomes `reset` or
  `init_reset` depending on module role.
- A function called from `probe` and not externally bound is a helper.

Acceptance:

- FunctionSpec role inference is correct for the selected sample drivers.
- Callback functions remain independent entry points.
- Pure helpers can be inlined or referenced without duplicating generated code.

## Milestone 4: Define Formal DeviceSpec in `.dspec`

Compose FunctionSpec modules into a device-level spec.

Proposed `.dspec` shape:

```text
device ftgpio010 {
  class gpio_controller

  state FtgpioState {
    base: MmioBase
    clk: Clock
    num_irqs: UInt
  }

  resource mmio0: MmioResource {
    bind base
  }

  resource clk0: ClockResource {
    required true
    bind clk
  }

  register GPIO_INT_EN: B4 at base + 0x20
  register GPIO_INT_CLR: B4 at base + 0x30
  register GPIO_DEBOUNCE_EN: B4 at base + 0x40

  invariant forall line: UInt.
    line < num_irqs -> valid_interrupt_line(line)

  function ftgpio_gpio_probe
  function ftgpio_gpio_ack_irq
  function ftgpio_gpio_mask_irq
}
```

Required concepts:

- Device class: GPIO, clock, virtio-mmio, AHCI, RTC, generic MMIO.
- State structure and abstract fields.
- Resource acquisition model.
- Register map.
- Function graph.
- Power and lifecycle phases.
- Device invariants.
- Backend-independent callback roles.

Acceptance:

- Build DeviceSpec for:
  - `gpio-ftgpio010`
  - `gpio-cadence`
  - simplified `virtio_mmio`
  - real Linux `virtio_mmio` as a harder benchmark.

## Milestone 5: Backend-Independent Driver IR

Normalize DeviceSpec into a generation-oriented IR.

This IR should separate:

- What the device does.
- Which resources it needs.
- Which abstract callbacks it exposes.
- Which RIS-backed functions implement behavior.
- Which backend adapter maps abstract concepts to runtime APIs.

Example abstract callbacks:

```yaml
callbacks:
  interrupt_ack:
    function: ftgpio_gpio_ack_irq
  gpio_get_direction:
    function: ftgpio_get_direction
  device_probe:
    function: ftgpio_gpio_probe
```

Acceptance:

- The same DeviceSpec can target at least two backends:
  - userspace harness
  - bare-metal C skeleton
- Linux remains a backend, not the core model.

## Milestone 5.5: Define Backend `.bind` Language

Define a formal binding language that maps `.dspec` concepts to backend APIs.

The `.bind` file is backend-specific and may mention concrete runtime types,
functions, callback tables, and code templates.

Linux binding example:

```text
backend linux for device ftgpio010 {
  include <linux/gpio/driver.h>
  include <linux/platform_device.h>

  type DeviceState -> "struct ftgpio_gpio"
  type LogicalIRQ -> "struct irq_data *"
  type MmioBase -> "void __iomem *"

  callback irq_chip.irq_ack = ftgpio_gpio_ack_irq
  callback irq_chip.irq_mask = ftgpio_gpio_mask_irq
  callback platform_driver.probe = ftgpio_gpio_probe

  map irq.line -> "irqd_to_hwirq(d)"
  map irq.owner -> "gpiochip_get_data(irq_data_get_irq_chip_data(d))"
  map dev.base -> "g->base"

  map MmioRead(B4) -> "readl"
  map MmioWrite(B4) -> "writel"
}
```

Bare-metal binding example:

```text
backend baremetal for device ftgpio010 {
  type DeviceState -> "struct ftgpio_dev"
  type LogicalIRQ -> "unsigned int"
  type MmioBase -> "uintptr_t"

  export interrupt_ack as "ftgpio_ack_irq"

  map irq.line -> "line"
  map irq.owner -> "dev"
  map dev.base -> "dev->base"

  map MmioRead(B4) -> "mmio_read32"
  map MmioWrite(B4) -> "mmio_write32"
}
```

Required binding concepts:

- Type mapping.
- Function name/export mapping.
- Callback table mapping.
- Resource acquisition mapping.
- State access mapping.
- MMIO primitive mapping.
- Error mapping.
- Locking and context mapping.

Acceptance:

- One `.dspec` can be paired with both Linux and bare-metal `.bind` files.
- Unsupported mappings produce explicit generator diagnostics.
- Backend-specific details do not leak into the core `.dspec`.

## Milestone 6: Code Generation Backends

Start with small, testable backends.

### Backend A: Userspace Harness

Purpose:

- Validate RIS execution behavior without kernel dependencies.
- Provide fake MMIO memory and trace logging.

Generated artifacts:

- Device state struct.
- Register constants.
- RIS-backed functions.
- Trace hooks for reads and writes.
- Unit-test scaffolding.

Acceptance:

- Generated harness compiles with normal `cc`.
- Running tests emits the same RIS trace shape as extracted.

### Backend B: Bare-Metal C

Purpose:

- Generate portable register-programming functions.

Generated artifacts:

- Device state struct with `uintptr_t base`.
- `read32/write32` wrappers.
- Init/reset/IRQ helper functions.
- No Linux framework glue.

Acceptance:

- Generated C compiles standalone.
- Register offsets and value expressions match RIS.

### Backend C: Linux Skeleton

Purpose:

- Generate a Linux driver scaffold when DeviceSpec has enough framework data.

Generated artifacts:

- `struct device_state`.
- `probe/remove`.
- `of_device_id`.
- framework ops table.
- RIS-backed callback bodies.

Acceptance:

- Generated code is buildable for simple platform GPIO examples.
- Unsupported semantics produce explicit TODOs, not silent incorrect code.

## Milestone 7: Verification Strategy

Use multiple levels of verification.

Static checks:

- Every RIS module referenced by FunctionSpec exists.
- Every symbolic register is in the register map.
- Every state binding resolves to a DeviceSpec field.
- Every backend-required callback is implemented.

Trace equivalence:

- Compare generated harness traces with extracted RIS.
- Verify operation order, address, width, value expression class, and guards.

Compile checks:

- Userspace harness: compile with `cc`.
- Bare-metal backend: compile with `cc -ffreestanding` where possible.
- Linux backend: compile with kernel build system for selected samples.

Regression set:

- `drivers/virtio_mmio/virtio_mmio.c`
- `drivers/test/gpio-ftgpio010.c`
- `linux/drivers/gpio/gpio-ftgpio010.c`
- `linux/drivers/gpio/gpio-cadence.c`
- `linux/drivers/virtio/virtio_mmio.c`

## Milestone 8: Quality Scoring

Add a generation readiness score.

Example:

```yaml
generation_readiness:
  ris_quality: 0.92
  function_spec_quality: 0.75
  device_spec_quality: 0.60
  backend_linux_ready: false
  backend_bare_metal_ready: true
  blockers:
    - dynamic register address in vm_get
    - missing DMA queue allocation semantics
    - incomplete error unwind model
```

Suggested scoring inputs:

- Percent symbolic addresses.
- Percent non-Top values.
- Percent functions with inferred roles.
- Percent parameters abstracted.
- Resource bindings resolved.
- Framework callbacks resolved.
- Error paths modeled.

Acceptance:

- CLI can report whether a driver is suitable for:
  - RIS-only generation
  - function skeleton generation
  - bare-metal backend
  - Linux backend

Important distinction:

- `backend_*_ready` means deterministic generation is expected to succeed.
- `llm_synthesis_ready` means the extracted artifacts are sufficient to ask an
  LLM to synthesize or repair a driver candidate under verification feedback.
- These are different gates. A driver can be `llm_synthesis_ready` even when
  deterministic Linux generation is not ready.

## Milestone 9: LLM-Assisted Driver Synthesis

Use large models as a synthesis and repair engine, constrained by formal specs
and verification feedback.

The goal is not one-shot natural-language generation. The goal is a closed loop:

```text
RIS + dspec + bind + facts + scaffold
  -> LLM generates candidate driver
  -> compile/static/trace checks
  -> feedback is converted into a repair prompt
  -> LLM patches candidate
  -> repeat until accepted or blocked
```

### Source Facts (`.facts`)

Add a source-facts artifact that captures information needed for reconstruction
but not appropriate for backend-independent `.dspec`.

Example:

```yaml
source: linux/drivers/gpio/gpio-ftgpio010.c
includes:
  - linux/gpio/driver.h
  - linux/platform_device.h
  - linux/clk.h
structs:
  ftgpio_gpio:
    fields:
      base: "void __iomem *"
      clk: "struct clk *"
      chip: "struct gpio_generic_chip"
constants:
  GPIO_INT_CLR: 0x30
callbacks:
  platform_driver.probe: ftgpio_gpio_probe
  irq_chip.irq_ack: ftgpio_gpio_ack_irq
resources:
  mmio0:
    acquisition: "devm_platform_ioremap_resource(pdev, 0)"
    binds_to: "g->base"
  clk0:
    acquisition: "devm_clk_get_enabled(dev, NULL)"
    binds_to: "g->clk"
source_snippets:
  probe_outline:
    - "devm_kzalloc"
    - "devm_platform_ioremap_resource"
    - "devm_gpiochip_add_data"
```

Facts should include:

- Include list.
- Local struct definitions and field types.
- Macro constants not captured as registers.
- Callback and ops table assignments.
- Resource acquisition calls.
- Error paths and return codes.
- Important helper calls and subsystem registration functions.
- Type-width facts, especially `u64`, `dma_addr_t`, `resource_size_t`.
- Existing source snippets around probe/remove/callback tables.

### LLM Input Bundle

For each backend target, create a deterministic input bundle:

```text
bundle/
  device.ris
  device.dspec
  device.<backend>.bind
  device.facts
  scaffold.c
  constraints.md
  verification.md
```

`constraints.md` should state hard requirements:

- Output must compile for the target backend.
- No undefined identifiers.
- No TODOs in accepted output.
- Callback signatures must match backend APIs.
- MMIO trace must match RIS where applicable.
- Do not invent registers not in `register_map` unless explicitly justified by
  facts.
- Preserve function roles and effects from `.dspec`.

### Deterministic Scaffold

Keep the current deterministic generators, but treat their output as a scaffold
for LLM repair rather than a final driver for complex backends.

Scaffold responsibilities:

- Emit register macros.
- Emit state structs.
- Emit RIS-backed function bodies.
- Emit obvious callback tables.
- Mark unsupported backend semantics explicitly.

The LLM is then responsible for:

- Correct callback adapters.
- Probe/remove resource lifecycle.
- Subsystem-specific registration glue.
- Type-width correction.
- Missing constants and includes.
- Error unwind.
- Removing TODOs.

### Verification Loop

Implement a repair loop:

```text
candidate.c
  -> compile
  -> static checks
  -> harness trace check
  -> optional backend-specific smoke tests
  -> if failure: summarize diagnostics and ask LLM for a patch
```

Verification outputs become structured feedback:

```yaml
compile:
  status: failed
  errors:
    - file: candidate.c
      line: 32
      message: "use of undeclared identifier 'dev'"
semantic:
  status: failed
  issues:
    - "platform_driver.probe is missing"
trace:
  status: passed
```

Acceptance:

- For userspace harness and bare-metal targets, LLM-repaired output compiles
  with strict warnings.
- For simple Linux platform GPIO samples, LLM-repaired output compiles against
  the selected kernel headers or kernel build tree.
- Generated output has no unresolved TODOs in accepted mode.
- RIS trace equivalence passes for generated harnesses.

### LLM Synthesis Readiness

Extend readiness scoring:

```yaml
generation_readiness:
  ris_quality: 0.92
  function_spec_quality: 0.75
  device_spec_quality: 0.60
  facts_quality: 0.70
  backend_bare_metal_ready: true
  backend_linux_ready: false
  llm_synthesis_ready: true
  blockers:
    - deterministic Linux backend missing callback adapter
```

`llm_synthesis_ready` should require:

- RIS quality above threshold.
- Function roles mostly inferred.
- Enough `.facts` to reconstruct backend glue.
- At least one deterministic scaffold.
- A compile/trace verification command for feedback.

It should not require deterministic Linux generation to be complete.

## Implementation Order

1. Add JSON/YAML export for RIS plus metadata.
2. Define the formal core IR and the minimal `.dspec` grammar together.
3. Add `FunctionSpec`, `DeviceSpec`, binding, and facts dataclasses in the same
   core spec module.
4. Add minimal `.bind` and `.facts` parsing/emission inside the core spec module
   first; split later only if grammar complexity requires it.
5. Add source-fact extraction as part of semantic inference, not as a separate
   file by default.
6. Add role inference from callback tables and function names.
7. Add state binding inference for MMIO base and driver private state.
8. Add userspace harness backend.
9. Add bare-metal backend.
10. Add Linux skeleton backend.
11. Add generation readiness scoring, including `llm_synthesis_ready`.
12. Add trace-equivalence tests.
13. Add LLM input bundle generation in a single synthesis module.
14. Add compile/static/trace verification feedback extraction to the same
    synthesis module unless it becomes independently reusable.
15. Add LLM repair loop orchestration, splitting synthesis only after the loop
    has stable sub-responsibilities.

## Near-Term Tasks

- Keep `extractor/spec.py` as the formal model module:
  - FunctionSpec and DeviceSpec data models.
  - Binding and source-facts data models.
  - Small parse/emit helpers for `.dspec`, `.bind`, and `.facts`.
- Keep `extractor/spec_infer.py` as the semantic inference module:
  - role inference
  - Linux callback-table recognition
  - MMIO/state binding inference
  - source facts extraction
- Keep `extractor/metrics.py` as the quality module:
  - RIS extraction metrics
  - generation readiness scoring
  - `llm_synthesis_ready`
- Add `generator/harness.py` for userspace harness generation.
- Add `generator/baremetal.py` for portable C generation.
- Add `generator/linux.py` only after FunctionSpec and DeviceSpec stabilize.
- Add one `synthesis.py` module later to assemble
  `(RIS, dspec, bind, facts, scaffold)`, normalize verification diagnostics, and
  run LLM-guided repair iterations. Do not split it into `bundle`, `verify`,
  and `repair_loop` until those responsibilities become large and separately
  testable.
- Add tests for:
  - callback role inference
  - MMIO base binding
  - source facts extraction
  - generated harness trace equivalence
  - strict-warning compile checks for generated harness/bare-metal code
  - readiness `llm_synthesis_ready`
  - readiness scoring

## Non-Goals For The First Version

- Fully regenerating arbitrary production Linux drivers.
- Inferring complex DMA ownership and cache coherency automatically.
- Inferring all locking semantics.
- Inferring all subsystem-specific contracts.
- Perfectly reconstructing source-level error handling.
- Trusting one-shot LLM output without compilation and trace verification.

The first useful target is a correct, backend-independent driver behavior spec
that can generate register-programming functions and harnesses reliably, plus
an LLM-assisted synthesis loop that can repair scaffolds into stronger driver
candidates under verification feedback.
