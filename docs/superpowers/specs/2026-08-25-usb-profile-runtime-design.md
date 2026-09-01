# USB Generic Profile Runtime Design

## Goal

Add USB as a built-in, data-driven driver profile without adding USB-specific
branches to the translation workflow or QEMU runner.

## Scope

The profile covers a conventional Linux `struct usb_driver` device driver that
matches a USB device ID and performs control or bulk transfers. The baseline
fixture is QEMU's in-tree `usb-serial` model, whose stable identity is
`0403:6001` and whose interface exposes one interrupt/status endpoint plus bulk
IN/OUT endpoints. Its deterministic guest-visible contract is a control status
read and bulk OUT; bulk IN requires an injected host input stream and is not a
required baseline assertion. The fixture is a QEMU device, not a claim that
all USB classes or real hardware are covered.

The profile must be selected from source evidence, render a schema-2 manifest,
compile the candidate as a Linux module, load the USB host modules, launch the
declared QEMU device, verify binding and a declared control/bulk transaction,
exercise a negative request, unload the candidate, and report the common
`accepted`/`failed`/`inconclusive` status. Missing USB kernel modules or an
invalid device identity must fail closed.

## Data Flow

```text
usb_driver source + usb_device_id
  -> usb-generic registry evidence
  -> profile plan and template merge
  -> Kbuild candidate
  -> QEMU qemu-xhci + usb-serial(0403:6001)
  -> USB probe/control/bulk subsystem tests
  -> accepted | failed | inconclusive
```

The generic matrix continues to consume only the manifest. The USB profile
owns its template, required kernel modules, fixture identity, and coverage
markers. The core runner only consumes existing `qemu_args`, `kernel_modules`,
binding, and subsystem-test fields.

## Failure Policy

- A source without USB registration evidence remains unknown to the default
  registry.
- A USB source without a parseable vendor/product identity is matched only for
  static analysis and returns `inconclusive` for runtime normalization.
- A missing `usbcore`, xHCI, or fixture capability is `inconclusive`, never an
  accepted dry run.
- A loaded but unbound driver, failed control/bulk transaction, kernel warning,
  or failed unload is `failed`.

## Verification Contract

The baseline USB manifest requires:

- `registration`, `probe`, `transfer`, and `unload` capabilities;
- USB bus binding to the candidate module;
- a control request returning the fixture's modem status;
- a bulk OUT transfer through the QEMU serial endpoint;
- rejection of an invalid endpoint or request;
- no QEMU kernel Oops or warning.

The matrix result proves this fixture contract only. It does not prove USB
HCD, gadget, hub, power-management, DMA, isochronous, or real-device
semantics for arbitrary USB drivers.
