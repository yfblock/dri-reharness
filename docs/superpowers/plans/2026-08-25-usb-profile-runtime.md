# USB Generic Profile Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a built-in USB profile that reaches the existing generic QEMU matrix through source evidence, a validated manifest, and a real QEMU USB transaction fixture.

**Architecture:** Extend the existing generic profile registry with `usb-generic`; keep device identity, QEMU arguments, kernel modules, and subsystem tests in a profile-owned schema-2 template. Use QEMU's `qemu-xhci` and `usb-serial` models, then let the unchanged manifest-driven runner execute the candidate and its tests.

**Tech Stack:** Python 3.12, pytest, Linux 7.1 Kbuild, QEMU 11, x86_64 initramfs, USB control/bulk transfers.

---

### Task 1: Lock the USB profile and manifest contract with failing tests

**Files:**
- Modify: `qa/tests/test_driver_profiles.py`
- Modify: `qa/tests/test_profile_runtime.py`
- Modify: `qa/tests/test_experiment_manifest.py`
- Create: `benchmarks/profile-templates/usb-generic.json`

- [ ] **Step 1: Add registry tests**

Assert that source containing `struct usb_driver`, `struct usb_device_id`,
`usb_control_msg`, and `USB_DEVICE(0x0403, 0x6001)` matches exactly
`usb-generic`, extracts `usb_driver.probe` and `usb_device`, and produces the
required `registration`, `probe`, `transfer`, and `unload` capabilities.

- [ ] **Step 2: Add manifest tests**

Load the USB template and assert it declares `qemu-xhci`, a `usb-serial`
QEMU argument, USB bus binding, `usbcore`, `xhci-hcd`, and `xhci-pci` kernel
modules, plus required subsystem tests and coverage IDs. Assert malformed
USB fixture identity remains rejected by the existing manifest validator.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_driver_profiles.py -k usb \
  qa/tests/test_profile_runtime.py -k usb \
  qa/tests/test_experiment_manifest.py -k usb
```

Expected result: the new tests fail because the default registry and USB
template do not exist yet.

### Task 2: Add the source-driven built-in profile

**Files:**
- Modify: `src/driver_profiles.py`
- Modify: `qa/tests/test_auto_driver.py`

- [ ] **Step 1: Add normalization tests**

Use a temporary renamed USB source and assert `normalize_input()` selects
`usb-generic`, preserves the source digest, and materializes the template's
runtime profile and fixture identity. Use a source with no `USB_DEVICE` ID and
assert the result is `inconclusive` with `runtime_identity`.

- [ ] **Step 2: Implement the minimal profile**

Register `_GenericBusProfile(profile_id="usb-generic", bus="usb", callback=
"usb_driver.probe", resource="usb_device", fixture_kind="qemu-usb", ... )`.
Recognize USB registration/resource/transfer tokens and extract the first
vendor/product pair from `USB_DEVICE(...)` or a `.idVendor/.idProduct` pair as
the fixture identity. Pass identity into fixture config and require
`vendor_id` and `product_id`; do not add a branch to `run_profile_matrix.py`.

- [ ] **Step 3: Run the profile tests**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_driver_profiles.py qa/tests/test_auto_driver.py -k usb
```

Expected result: all USB registry and normalization tests pass.

### Task 3: Add the QEMU USB candidate and subsystem exerciser

**Files:**
- Create: `benchmarks/drivers/fixtures/reharness-usb-sensor.c`
- Create: `qa/native-tests/usb_transaction_test.c`
- Create: `benchmarks/experiments/reharness-usb.json`
- Modify: `benchmarks/profile-templates/usb-generic.json`
- Modify: `platform/kernel/linux-x86_64.config`

- [ ] **Step 1: Add the negative runtime test first**

Make the native test issue a valid control-status request and bulk OUT
transfer, then issue an invalid endpoint request and require `-ENODEV` or
`-EINVAL`. Require markers `USB_CONTROL_PASS`, `USB_BULK_OUT_PASS`, and
`USB_INVALID_ENDPOINT_PASS`.

- [ ] **Step 2: Add the deterministic USB driver fixture**

Implement a Linux `usb_driver` matching `USB_DEVICE(0x0403, 0x6001)`. In
probe, retain a reference to `interface_to_usbdev(interface)`, issue the FTDI
GET_MODEM_STATUS control request, create `/dev/reharness-usb-control`, and log
`REHARNESS_USB_DRIVER_PROBE`. Its ioctl path must perform bulk OUT on endpoint
2, validate endpoint numbers, and release the USB reference and misc device in
disconnect.

- [ ] **Step 3: Declare the QEMU manifest**

Use `machine: pc`, `bus: usb`, `device: qemu-xhci`, `qemu_args` containing
`-device qemu-xhci,id=reharness_xhci` and
`-device usb-serial,bus=reharness_xhci.0`, and `kernel_modules` containing the
USB core and xHCI modules built from the pinned kernel. Declare a required USB
binding and the native transaction test.

- [ ] **Step 4: Enable only the required kernel capabilities**

Set USB host support, xHCI PCI support, and the module form needed by the
manifest in the pinned config; USB core remains built into the kernel so direct
`insmod` does not need dependency resolution. Rebuild the existing
kernel build directory with the repository's normal Kbuild command and verify
the expected `.ko` files exist before running QEMU.

### Task 4: Integrate the USB case into the generic matrix

**Files:**
- Modify: `qa/tests/test_profile_matrix.py`
- Modify: `README.md`
- Modify: `REPRO.md`

- [ ] **Step 1: Add matrix discovery tests**

Assert that the no-argument required profile set now includes `usb-generic`,
and that explicit USB manifest discovery derives exactly that profile without
special-casing its name.

- [ ] **Step 2: Add the baseline manifest to the default experiment set**

Place `reharness-usb.json` in `benchmarks/experiments`; rely on registry-derived
default profile IDs and the existing generic `run_case()` path.

- [ ] **Step 3: Document the evidence boundary**

Document USB as one representative profile and explicitly state that QEMU
`usb-serial` coverage does not imply HCD, gadget, hub, isochronous, or
hardware-in-the-loop coverage.

### Task 5: Verify and audit the generic framework

**Files:**
- Review: `src/driver_profiles.py`
- Review: `qa/verification/run_profile_matrix.py`
- Review: `scripts/qemu/qemu_run.sh`

- [ ] **Step 1: Run focused tests and static checks**

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_driver_profiles.py qa/tests/test_auto_driver.py \
  qa/tests/test_profile_matrix.py qa/tests/test_profile_runtime.py \
  qa/tests/test_experiment_manifest.py
git diff --check
bash -n run.sh scripts/qemu/qemu_run.sh qa/verification/run_qemu_experiments.sh
python3 -m compileall -q src qa
```

- [ ] **Step 2: Run the USB QEMU case**

```bash
./run.sh profile-matrix --required-profile usb-generic \
  --manifest benchmarks/experiments/reharness-usb.json \
  --output artifacts/profile-matrix-usb
```

Expected result: `usb-generic: accepted`, all three USB markers are present,
the candidate and required modules unload with return code 0, and no kernel
Oops or warning is reported.

- [ ] **Step 3: Run the existing matrix and report residual gaps**

```bash
./run.sh profile-matrix
./run.sh test
```

The final report must distinguish accepted profile evidence from the known
repository-layout audit failures and must not claim whole-subsystem coverage.
