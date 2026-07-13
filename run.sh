#!/usr/bin/env bash
# reharness — libclang + dataflow/taint RIS extractor.
# Output is the .ris spec language only (no JSON).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
PY="${PYTHON:-python3}"

banner() { echo "reharness — libclang + dataflow/taint RIS extraction (.ris spec language)"; }

usage() {
  cat <<EOF
Usage: $0 <command> [args]

Commands:
  extract <src> [out.ris]   extract RIS spec language from a C driver
  show <ris>                print a .ris file
  spec <src> [out.dspec]    infer & print backend-independent .dspec
  gen <src> <backend> [out.c]   generate C (backend: harness|baremetal|linux)
  driver <src> [outdir]         one-shot full pipeline (RIS+dspec+bind+backends+trace)
  facts <src>                  source facts (.facts) for LLM synthesis
  bundle <src> [backend] [outdir]   build LLM input bundle (RIS+dspec+bind+facts)
  e2e <src> [target] [skip_synth]   end-to-end: extract → Pi synth → compile → QEMU → trace
  metrics <src>             per-module extraction quality metrics
  score <src>               generation readiness scoring
  pipeline <src> [out.ris]  extract (alias of extract)
  demo                      extract gpio-ftgpio010 → output/demo/gpio-ftgpio010.ris
  compare [-j N]              per-driver extraction stats (N=parallel jobs, 0=auto)
  test                      run the test suite

No JSON is produced. The .ris spec language is the sole RIS output format.
EOF
}

cmd_extract() {
  local src="${1:-}" out="${2:-output/ris.ris}"
  [ -n "$src" ] || { echo "usage: $0 extract <src> [out.ris]"; exit 1; }
  mkdir -p "$(dirname "$out")"
  $PY -m extractor extract -s "$src" -o "$out"
}

cmd_show() { cat "${1:?need .ris file}"; }

cmd_spec() {
  local src="${1:?need src}" out="${2:-}"
  if [ -n "$out" ]; then $PY -m extractor spec -s "$src" -o "$out"
  else $PY -m extractor spec -s "$src"; fi
}

cmd_gen() {
  local src="${1:?need src}" backend="${2:?need backend (harness|baremetal|linux)}" out="${3:-}"
  if [ -n "$out" ]; then $PY -m extractor gen -s "$src" -b "$backend" -o "$out"
  else $PY -m extractor gen -s "$src" -b "$backend"; fi
}

cmd_metrics() { $PY -m extractor metrics -s "${1:?need src}"; }
cmd_facts()   { $PY -m extractor facts   -s "${1:?need src}" ${2:+-o "$2"}; }
cmd_bundle()  { $PY -m extractor bundle  -s "${1:?need src}" -b "${2:-harness}" ${3:+-o "$3"}; }
cmd_score()   { $PY -m extractor score   -s "${1:?need src}"; }
cmd_driver()  { $PY -m extractor driver  -s "${1:?need src}" ${2:+-o "$2"}; }
cmd_e2e()     { bash "$HERE/run_e2e.sh" "$@"; }

cmd_pipeline() {
  local src="${1:?need src}" out="${2:-output/ris.ris}"
  cmd_extract "$src" "$out"
}

cmd_demo() {
  cmd_extract drivers/test/gpio-ftgpio010.c output/demo/gpio-ftgpio010.ris
}

cmd_compare() { $PY verification/compare.py "$@"; }
cmd_test()    { $PY tests/test_extractor.py; }

banner
case "${1:-help}" in
  extract)   shift; cmd_extract "$@";;
  show)      shift; cmd_show "$@";;
  spec)      shift; cmd_spec "$@";;
  gen)       shift; cmd_gen "$@";;
  driver)    shift; cmd_driver "$@";;
  facts)     shift; cmd_facts "$@";;
  bundle)    shift; cmd_bundle "$@";;
  e2e)       shift; cmd_e2e "$@";;
  metrics)   shift; cmd_metrics "$@";;
  score)     shift; cmd_score "$@";;
  pipeline)  shift; cmd_pipeline "$@";;
  demo)      shift; cmd_demo "$@";;
  compare)   shift; cmd_compare "$@";;
  test)      shift; cmd_test "$@";;
  help|-h|--help) usage;;
  *) echo "unknown command: $1"; usage; exit 1;;
esac
