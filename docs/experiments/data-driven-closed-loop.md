# Data-Driven Closed Loop

Run an experiment from a validated manifest:

```sh
./run.sh experiment benchmarks/experiments/edu.json
```

The runner loads the source and trace contract from the manifest, writes an
evidence package, asks Pi for a candidate, and then executes compile,
baseline, candidate, and trace-comparison stages. Compile, runtime, and trace
failures are serialized as structured feedback and can be sent back to Pi
until the manifest limits are exhausted. Extraction, contract, and
infrastructure failures stop the run without guessing a repair.

Each run is append-only under `artifacts/experiments/<name>/`:

- `experiment.json` contains the manifest digest, status, and stage history.
- `iterations/NN-<stage>.json` contains one immutable stage record.
- Runtime adapters store normalized original and candidate trace artifacts.

Target facts belong in the manifest or an explicitly selected runtime
adapter. The generic runner and Pi bridge do not infer a subsystem, driver
name, compatible string, or private register constant.

Runtime policy is split into three manifest sections:

- `runtime.pci_identity` supplies vendor/device identity to PCI generation;
- `runtime.safety_policy` supplies forbidden tokens and reject/rewrite rules
  to the generic source sanitizer;
- `runtime.qemu` supplies machine, bus, device model, module, probe pattern,
  timeout, and optional QEMU arguments.

The deterministic QEMU verification command discovers every JSON manifest in
`benchmarks/experiments/`; adding an experiment does not require a new shell
branch. Device-specific wrapper scripts and demo aliases are intentionally not
part of the public interface. Linux callback/API semantic tables remain in the
generator because they model stable kernel interfaces, not a device identity.
