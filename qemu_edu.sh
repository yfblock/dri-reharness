#!/bin/bash
# 薄包装: edu PCI 驱动 → qemu_run.sh
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODULE="${MODULE:-edu_drv}"
exec "$PROJECT_DIR/qemu_run.sh" "$MODULE" \
    -b pci -d edu \
    -e test/edu_trace_test -a "/dev/$MODULE" \
    -p "probed|edu device id|edu probed" \
    -t "${1:-90}"
