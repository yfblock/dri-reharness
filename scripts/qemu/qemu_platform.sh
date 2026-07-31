#!/bin/bash
# 薄包装: platform 驱动 → qemu_run.sh
# 用法: qemu_platform.sh <module> <registrar_target> [timeout]
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODULE="${1:?need module}"
TARGET="${2:?need registrar_target}"
TIMEOUT="${3:-90}"
EXERCISER=""
EXERCISER_ARGS=""
# gpio 驱动自动加 gpio_trace_test
if [ -f "$PROJECT_DIR/test/gpio_trace_test" ]; then
    EXERCISER="-e test/gpio_trace_test -a /dev/gpiochip0"
fi
exec "$PROJECT_DIR/qemu_run.sh" "$MODULE" \
    -b platform -r "$TARGET" \
    $EXERCISER \
    -p "probed|registered|gpiochip" \
    -t "$TIMEOUT"
