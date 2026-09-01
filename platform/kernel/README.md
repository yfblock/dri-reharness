# Reproducible Linux kernel setup

`../../vendor/linux/` is a populated Git submodule pinned to the exact upstream Linux
commit used by the experiments.  The preparation script applies the repository-owned
`amba-compile-test.patch` before Kconfig evaluation so the x86 synthetic AMBA profile
can exercise the generic bus core; this is an experiment-only compile-test enablement,
not an assertion that x86 provides AMBA hardware.

Initialize the submodule after cloning with:

```sh
git submodule update --init --recursive
```

The experiment kernel is built from that source tree with the checked-in
`linux-x86_64.config` configuration and `arch-have-trace-mmio.patch` patch:

```sh
./tools/build/prepare_kernel.sh build
```

The script performs an out-of-tree build in `platform/kernel/build/`, leaving the Linux
submodule clean.  The optional patch is retained as provenance for the earlier
kernel-level MMIO tracing experiment; the standard generated-driver trace
instrumentation does not require it.
