#!/bin/bash
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
exec "$ROOT/scripts/e2e/run_e2e.sh" \
  "$ROOT/benchmarks/drivers/baseline/edu.c" edu "$@"
