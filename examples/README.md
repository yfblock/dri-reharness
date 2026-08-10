# Generated driver examples

These files are deterministic outputs from the current reharness pipeline,
using benchmarks/drivers/baseline/edu.c as input. Each C backend is emitted
as a .h/.c pair; the Rust backend is a single .rs file.

Regenerate with:

    PYTHONPATH=src python3 -m extractor gen -s benchmarks/drivers/baseline/edu.c -b harness --pair -o examples/edu/edu_harness
    PYTHONPATH=src python3 -m extractor gen -s benchmarks/drivers/baseline/edu.c -b baremetal --pair -o examples/edu/edu_baremetal
    PYTHONPATH=src python3 -m extractor gen -s benchmarks/drivers/baseline/edu.c -b linux --pair --manifest benchmarks/experiments/edu.json -o examples/edu/edu_linux
    PYTHONPATH=src python3 -m extractor gen -s benchmarks/drivers/baseline/edu.c -b rust_baremetal -o examples/edu/edu_rust_baremetal.rs

| File | Backend | Description |
| --- | --- | --- |
| edu_harness.h / edu_harness.c | Userspace harness | Fake MMIO + trace logging, compiles with cc -Wall |
| edu_baremetal.h / edu_baremetal.c | Bare-metal | Portable C, compiles with cc -ffreestanding -c |
| edu_linux.h / edu_linux.c | Linux kernel module | PCI/platform driver, builds via Kbuild |
| edu_rust_baremetal.rs | Rust bare-metal | Portable Rust no_std, compiles with rustc --crate-type lib |
