#!/bin/bash
src="${1:-drivers/test/gpio-ftgpio010.c}"
shift 2>/dev/null || true
exec "$(cd "$(dirname "$0")" && pwd)/run_e2e.sh" "$src" platform "$@"
