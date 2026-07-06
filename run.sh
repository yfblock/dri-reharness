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
  pipeline <src> [out.ris]  extract (alias of extract)
  demo                      extract gpio-ftgpio010 → output/demo/gpio-ftgpio010.ris
  compare                   per-driver extraction stats over drivers/test/*.c
  test                      run the test suite

No JSON is produced. The .ris spec language is the sole output format.
EOF
}

cmd_extract() {
  local src="${1:-}" out="${2:-output/ris.ris}"
  [ -n "$src" ] || { echo "usage: $0 extract <src> [out.ris]"; exit 1; }
  mkdir -p "$(dirname "$out")"
  $PY -m extractor extract -s "$src" -o "$out"
}

cmd_show() {
  local ris="${1:?need .ris file}"
  cat "$ris"
}

cmd_pipeline() {
  local src="${1:?need src}" out="${2:-output/ris.ris}"
  cmd_extract "$src" "$out"
}

cmd_demo() {
  cmd_extract drivers/test/gpio-ftgpio010.c output/demo/gpio-ftgpio010.ris
}

cmd_compare() {
  $PY verification/compare.py
}

cmd_test() {
  $PY tests/test_extractor.py
}

banner
case "${1:-help}" in
  extract)   shift; cmd_extract "$@";;
  show)      shift; cmd_show "$@";;
  pipeline)  shift; cmd_pipeline "$@";;
  demo)      shift; cmd_demo "$@";;
  compare)   shift; cmd_compare "$@";;
  test)      shift; cmd_test "$@";;
  help|-h|--help) usage;;
  *) echo "unknown command: $1"; usage; exit 1;;
esac
