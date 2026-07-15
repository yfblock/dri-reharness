# Reproducible Linux kernel setup

`../linux/` is a populated Git submodule pinned to the exact upstream Linux
commit used by the experiments.  Initialize it after cloning with:

```sh
git submodule update --init --recursive
```

The experiment kernel is built from that source tree with the checked-in
`linux-x86_64.config` configuration and `arch-have-trace-mmio.patch` patch:

```sh
./tools/prepare_kernel.sh build
```

The script performs an out-of-tree build in `kernel/build/`, leaving the Linux
submodule clean.  The optional patch is retained as provenance for the earlier
kernel-level MMIO tracing experiment; the standard generated-driver trace
instrumentation does not require it.
