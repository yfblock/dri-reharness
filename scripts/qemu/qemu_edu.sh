#!/bin/bash
# Thin wrapper for the educational PCI target.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
MODULE="${1:-${MODULE:-edu_drv}}"
TIMEOUT="${2:-90}"
exec "$SCRIPT_DIR/qemu_run.sh" "$MODULE" \
    -b pci -d edu \
    -e qa/native-tests/edu_trace_test -a "/dev/$MODULE" \
    -p "probed|edu device id|edu probed" \
    -t "$TIMEOUT"
