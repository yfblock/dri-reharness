#!/bin/bash
# 薄包装: edu PCI 驱动 → qemu_run.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
MODULE="${MODULE:-edu_drv}"
exec "$SCRIPT_DIR/qemu_run.sh" "$MODULE" \
    -b pci -d edu \
    -e test/edu_trace_test -a "/dev/$MODULE" \
    -p "probed|edu device id|edu probed" \
    -t "${1:-90}"
