#!/usr/bin/env bash
# reharness — libclang + dataflow/taint RIS extractor.
# Output is the .ris spec language only (no JSON).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/qa:$ROOT/qa/verification${PYTHONPATH:+:$PYTHONPATH}"
PY="${PYTHON:-python3}"
OUTPUT_ROOT="$ROOT/artifacts/output"

banner() { echo "reharness — libclang + dataflow/taint RIS extraction (.ris spec language)"; }

usage() {
  cat <<EOF
Usage: $0 <command> [args]

Commands:
  extract <src> [out.ris]   extract RIS spec language from a C driver
  show <ris>                print a .ris file
  spec <src> [out.dspec]    infer & print backend-independent .dspec
  gen <src> <backend> [out.c]   generate C (backend: harness|baremetal|linux)
                                  backend rust_baremetal outputs .rs
  gen-pair <src> <backend> [out_base]   generate .h + .c pair
  driver <src> [outdir]         one-shot full pipeline (RIS+dspec+bind+backends+trace)
  facts <src>                  source facts (.facts) for LLM synthesis
  bundle <src> [backend] [outdir]   build LLM input bundle (RIS+dspec+bind+facts)
  metrics <src>             per-module extraction quality metrics
  score <src>               generation readiness scoring
  reliability [src ...]     machine-readable scoped RIS reliability report
  pipeline <src> [out.ris]  extract (alias of extract)
  compare [-j N]              per-driver extraction stats (N=parallel jobs, 0=auto)
  test                      run the test suite
  e2e <src> [target] [skip_synth]   full synthesis and runtime workflow
  experiment <manifest> [options]   manifest-driven closed-loop experiment
  qemu <module> [options]   run a synthesized module under QEMU
  qemu-experiments          run the reproducible QEMU experiment suite
  log-event <message ...>   append an engineering timeline event

The .ris spec language remains the sole RIS artifact format; reliability
emits a separate audit JSON and does not replace the RIS.
EOF
}

cmd_extract() {
  local src="${1:-}" out="${2:-$OUTPUT_ROOT/ris.ris}"
  [ -n "$src" ] || { echo "usage: $0 extract <src> [out.ris]"; exit 1; }
  mkdir -p "$(dirname "$out")"
  "$PY" -m extractor extract -s "$src" -o "$out"
}

cmd_show() { cat "${1:?need .ris file}"; }

cmd_spec() {
  local src="${1:?need src}" out="${2:-}"
  if [ -n "$out" ]; then "$PY" -m extractor spec -s "$src" -o "$out"
  else "$PY" -m extractor spec -s "$src"; fi
}

cmd_gen() {
  local src="${1:?need src}" backend="${2:?need backend (harness|baremetal|linux)}" out="${3:-}"
  if [ -n "$out" ]; then "$PY" -m extractor gen -s "$src" -b "$backend" -o "$out"
  else "$PY" -m extractor gen -s "$src" -b "$backend"; fi
}

cmd_gen_pair() {
  local src="${1:?need src}" backend="${2:?need backend (harness|baremetal|linux)}" out="${3:-}"
  if [ -n "$out" ]; then "$PY" -m extractor gen -s "$src" -b "$backend" --pair -o "$out"
  else "$PY" -m extractor gen -s "$src" -b "$backend" --pair; fi
}

cmd_metrics() { "$PY" -m extractor metrics -s "${1:?need src}"; }
cmd_facts()   { "$PY" -m extractor facts   -s "${1:?need src}" ${2:+-o "$2"}; }
cmd_bundle()  { "$PY" -m extractor bundle  -s "${1:?need src}" -b "${2:-harness}" ${3:+-o "$3"}; }
cmd_score()   { "$PY" -m extractor score   -s "${1:?need src}"; }
cmd_reliability() { "$PY" qa/verification/reliability_report.py "$@"; }
cmd_driver()  { "$PY" -m extractor driver  -s "${1:?need src}" ${2:+-o "$2"}; }
cmd_e2e() { bash scripts/e2e/run_e2e.sh "$@"; }
cmd_experiment() {
  "$PY" qa/verification/run_experiment.py "$@" --adapter-module "${REHARNESS_ADAPTER_MODULE:-verification.runtime_adapters}"
}
cmd_qemu() { bash scripts/qemu/qemu_run.sh "$@"; }
cmd_qemu_experiments() { bash qa/verification/run_qemu_experiments.sh "$@"; }
cmd_log_event() { bash scripts/maintenance/log_event.sh "$@"; }

cmd_pipeline() {
  local src="${1:?need src}" out="${2:-$OUTPUT_ROOT/ris.ris}"
  cmd_extract "$src" "$out"
}

cmd_compare() { "$PY" qa/verification/compare.py "$@"; }
cmd_test()    {
  "$PY" qa/verification/check_generalization_guard.py
  "$PY" qa/tests/test_repository_layout.py
  "$PY" qa/tests/test_run_dispatcher.py
  "$PY" qa/tests/test_repository_paths.py
  "$PY" qa/tests/test_extractor.py
  "$PY" qa/tests/test_generated_c_ast_oracle.py
  "$PY" qa/tests/test_linux_registration_ast_oracle.py
  "$PY" qa/tests/test_backend_lowering_plan.py
  "$PY" -m pytest -q qa/tests/test_experiment_manifest.py qa/tests/test_experiment_protocol.py \
    qa/tests/test_experiment_runner.py qa/tests/test_pi_bridge_protocol.py \
    qa/tests/test_trace_protocol.py qa/tests/test_trace_compare.py \
    qa/tests/test_runtime_adapters.py qa/tests/test_no_hardcoding.py
  "$PY" qa/tests/test_metrics_c20_readiness.py
  "$PY" qa/tests/test_dataflow_read_return.py
  "$PY" qa/tests/test_device_spec_json.py
}

banner
case "${1:-help}" in
  extract)   shift; cmd_extract "$@";;
  show)      shift; cmd_show "$@";;
  spec)      shift; cmd_spec "$@";;
  gen)       shift; cmd_gen "$@";;
  gen-pair)  shift; cmd_gen_pair "$@";;
  driver)    shift; cmd_driver "$@";;
  facts)     shift; cmd_facts "$@";;
  bundle)    shift; cmd_bundle "$@";;
  metrics)   shift; cmd_metrics "$@";;
  score)     shift; cmd_score "$@";;
  reliability) shift; cmd_reliability "$@";;
  pipeline)  shift; cmd_pipeline "$@";;
  compare)   shift; cmd_compare "$@";;
  test)      shift; cmd_test "$@";;
  e2e)       shift; cmd_e2e "$@";;
  experiment) shift; cmd_experiment "$@";;
  qemu)      shift; cmd_qemu "$@";;
  qemu-experiments) shift; cmd_qemu_experiments "$@";;
  log-event) shift; cmd_log_event "$@";;
  help|-h|--help) usage;;
  *) echo "unknown command: $1"; usage; exit 1;;
esac
