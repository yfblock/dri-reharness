#!/usr/bin/env bash
# Deterministic QEMU experiments discovered from validated manifests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/qa:$ROOT/qa/verification${PYTHONPATH:+:$PYTHONPATH}"
KERNELDIR="${KERNELDIR:-$ROOT/platform/kernel/build}"
RESULTS="${RESULTS:-$ROOT/research/experiments/results}"
mkdir -p "$RESULTS"

if [ ! -f "$KERNELDIR/arch/x86/boot/bzImage" ]; then
    ./tools/build/prepare_kernel.sh build
fi

write_makefile() {
    printf 'obj-m += %s.o\n' "$2" > "$1/Makefile"
}

build_module() {
    make -C "$KERNELDIR" M="$1" clean >/dev/null
    make -C "$KERNELDIR" M="$1" modules >/dev/null
}

build_exerciser() {
    "${CC:-cc}" -static -O2 -Wall -Wextra -o "$2" "$1"
}

INFO_FILE="$(mktemp)"
ROWS_FILE="$(mktemp)"
overall_rc=0
trap 'rm -f "$INFO_FILE" "$ROWS_FILE"' EXIT

for manifest in benchmarks/experiments/*.json; do
    eval "$(python3 - "$manifest" <<'PY'
import shlex, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from experiment_manifest import load_manifest
m = load_manifest(sys.argv[1], repo_root=Path.cwd())
def emit(name, value):
    print(f"{name}={shlex.quote(str(value))}")
emit("MANIFEST_NAME", m.name)
emit("SOURCE", str(m.source.path.relative_to(Path.cwd())))
emit("BACKEND", m.compile.backend)
emit("MODULE", m.runtime.module)
emit("BUS", m.runtime.bus)
emit("TEST", str(m.test.executable.relative_to(Path.cwd())))
emit("CALLS", "|".join(m.trace.exercised_calls))
PY
)"

    out_dir="$ROOT/artifacts/output/$MODULE"
    spec_dir="$ROOT/artifacts/output/manifest-$MANIFEST_NAME"
    mkdir -p "$out_dir" "$spec_dir"
    python3 -m extractor gen -s "$SOURCE" -b "$BACKEND" -o "$out_dir/$MODULE.c"
    if [ "${MANIFEST_NAME:-}" ] && python3 - "$manifest" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from experiment_manifest import load_manifest
raise SystemExit(0 if load_manifest(sys.argv[1], repo_root=Path.cwd()).trace.instrument else 1)
PY
    then
        python3 tools/source/instrument_mmio.py "$out_dir/$MODULE.c"
    fi
    write_makefile "$out_dir" "$MODULE"
    build_module "$out_dir"

    test_source="$ROOT/${TEST}.c"
    if [ -f "$test_source" ]; then
        build_exerciser "$test_source" "$ROOT/$TEST"
    fi
    if [ "$BUS" = "platform" ]; then
        make -C qa/verification/device-registrar KERNELDIR="$KERNELDIR" >/dev/null
    fi

    serial="$RESULTS/${MANIFEST_NAME}-serial.log"
    judge="$RESULTS/${MANIFEST_NAME}-judge.txt"
    qemu_out="/tmp/reharness_qemu_${MANIFEST_NAME}.txt"
    set +e
    RH_QEMU_OUT="$qemu_out" bash scripts/qemu/qemu_run.sh --manifest "$manifest" \
        | tr -d '\r' | sed 's/[[:blank:]]*$//' | tee "$judge"
    qemu_rc=${PIPESTATUS[0]}
    set -e
    tr -d '\r' < "$qemu_out" | sed 's/[[:blank:]]*$//' > "$serial"
    trace_ok=true
    if [ -n "$CALLS" ]; then
        python3 -m extractor extract -s "$SOURCE" -o "$spec_dir/$MANIFEST_NAME.ris" \
            --json-output "$spec_dir/$MANIFEST_NAME.formal.json" >/dev/null
        exercised="${CALLS//|/,}"
        python3 tools/reporting/trace_match.py "$serial" \
            --formal-json "$spec_dir/$MANIFEST_NAME.formal.json" \
            --exercised-calls "$exercised" 2>&1 | tee "$RESULTS/${MANIFEST_NAME}-trace.txt"
        grep -q TRACE_MATCH_OK "$RESULTS/${MANIFEST_NAME}-trace.txt" || trace_ok=false
    fi
    python3 - "$ROWS_FILE" "$manifest" "$qemu_rc" "$trace_ok" <<'PY'
import json, sys
path, manifest, qemu_rc, trace_ok = sys.argv[1:]
with open(path, "a", encoding="utf-8") as handle:
    json.dump({"manifest": manifest, "qemu_returncode": int(qemu_rc),
               "trace_ok": trace_ok == "true"}, handle)
    handle.write("\n")
PY
    if [ "$qemu_rc" -ne 0 ] || [ "$trace_ok" != true ]; then
        overall_rc=1
    fi
done

python3 - "$ROWS_FILE" "$RESULTS/qemu.json" <<'PY'
import datetime, json, os, subprocess, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
experiments = {}
for row in rows:
    name = os.path.splitext(os.path.basename(row["manifest"]))[0]
    experiments[name] = {"probe": row["qemu_returncode"] == 0,
                         "trace_oracle": row["trace_ok"]}
data = {"schema": 1, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reharness_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "experiments": experiments}
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

if [ "$overall_rc" -eq 0 ]; then
    echo "QEMU_EXPERIMENTS_OK"
else
    echo "QEMU_EXPERIMENTS_FAILED" >&2
fi
exit "$overall_rc"
