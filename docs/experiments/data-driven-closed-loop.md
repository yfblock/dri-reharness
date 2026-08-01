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
