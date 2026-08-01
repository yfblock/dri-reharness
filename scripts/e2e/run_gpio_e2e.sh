#!/bin/bash
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
src="${1:-$ROOT/benchmarks/drivers/baseline/gpio-ftgpio010.c}"
shift 2>/dev/null || true
exec "$ROOT/scripts/e2e/run_e2e.sh" "$src" gpio "$@"
