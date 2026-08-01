# C23: owner-qualified public callback semantics

## Goal

After the zero-shot-v2 callback ownership stage, four holdout cases retained
`missing_role` even though libclang had already proved the callback owner and
field.  This stage improves semantic inference without consulting driver
names, basenames, compatible strings, Kconfig symbols, or private prefixes.

## Mechanism

Public kernel callback ABIs now support owner-qualified role contracts.  The
owner is the AST-declared structure type and the field is the referenced
function-pointer member.  Owner qualification prevents a private structure
field such as `set_clock` from acquiring executable backend intent merely
because it shares a familiar name.

The first contracts cover:

- `clk_ops.is_prepared` as a status query;
- SDHCI clock, voltage, bus-width, signaling, power, and hardware-reset
  callbacks;
- MMC voltage-switch, tuning, enhanced-strobe, and request callbacks,
  preserving atomic context for `request_atomic`.

The Linux emitter consumes the same public contracts.  It now emits
`clk_ops.is_prepared` and the supported SDHCI voltage/clock/bus-width/
signaling/power/reset fields with canonical kernel signatures.  Required
headers are selected from referenced public APIs; for example,
`read_poll_timeout*` adds `<vendor/linux/iopoll.h>`.  Poll accessor identifiers are
also excluded from scalar-local inference, preventing generated declarations
from shadowing functions passed to polling macros.

Every other owner/field continues through the existing fail-closed path.  In
particular, source-private callback owners retain binding evidence with role
`unknown`.

## Exact-context holdout result

Focused extraction using the frozen zero-shot-v2 compile database changes the
role result for three of the four original `missing_role` cases:

| Case | Callback evidence | Result |
| --- | --- | --- |
| clk-si544 | `clk_ops.is_prepared` | `get_status` |
| sdhci-milbeaut | `sdhci_ops.voltage_switch` | `write_config` |
| sdhci-sprd | public `sdhci_ops` and `mmc_host_ops` fields | typed write/reset roles |
| virtio-pci-legacy | private `virtio_pci_device.del_vq` | remains `unknown` |

The negative virtio result is intentional.  A private function-pointer field
does not prove that it is equivalent to the public
`virtio_config_ops.del_vqs` lifecycle or that a backend may register it.

Full focused driver pipelines confirm that `clk-si544` keeps all three
backends compilable and that `sdhci-sprd` keeps its Linux module compilable.
The pre-existing SPRD harness/bare-metal accessor runner failures and strict
semantic blockers remain visible; this stage does not reclassify them as
success.

## USB lifecycle robustness

The in-progress source-derived USB HCD lifecycle oracle is now safe in the
presence of synthetic subsystem functions, which deliberately have no
libclang cursor.  Non-USB drivers take a source-token fast path, and lifecycle
call-path enumeration is reverse-pruned, cycle-free, bounded, and fail-closed.
These changes prevent a general-purpose analysis pass from regressing GPIO or
clock extraction while retaining explicit ambiguity and search-bound errors.

## Verification

- generalization guards pass for zero-shot-v1 and zero-shot-v2;
- all 136 pre-change core tests pass in bounded chunks; the 3 new core tests
  and affected src/generator/DWC2 regressions pass in focused reruns;
- 8 generated-C AST, 10 Linux registration AST, 21 lowering-plan, 1 readiness,
  2 read-provenance, and 5 DeviceSpec JSON tests pass;
- focused exact-context extraction confirms the three positive holdout role
  changes and the private virtio negative boundary;
- FTGPIO extraction remains 35 exact symbolic operations with no diagnostic.
- generated-C AST and Linux registration suites remain 8/8 and 10/10.

The monolithic `./run.sh test` invocation exceeded the managed command runtime
and was killed after entering the core suite; the pre-change core suite passed
when split across four fresh processes, and the final delta was then covered by
focused tests and exact-context driver pipelines.

## Remaining boundary

Role inference is not runtime registration or behavioral equivalence.  Linux
generation still needs independently verified object attachment and lifecycle
routes for many SDHCI/MMC callbacks.  Private virtio teardown requires a
cross-TU ownership contract linking the private `del_vq` field to the public
`del_vqs` route; adding a name-only role would be unsound.
