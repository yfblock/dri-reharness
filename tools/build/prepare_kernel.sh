#!/usr/bin/env bash
# Prepare or fully build the pinned experiment kernel without dirtying vendor/linux/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
SRC="${KERNEL_SOURCE:-$ROOT/vendor/linux}"
OUT="${KERNEL_BUILD_DIR:-$ROOT/platform/kernel/build}"
CONFIG="${KERNEL_CONFIG:-$ROOT/platform/kernel/linux-x86_64.config}"
MODE="${1:-prepare}"
JOBS="${JOBS:-$(nproc)}"

# The pinned kernel normally selects ARM_AMBA from ARM/ARM64 architecture
# Kconfig.  The x86 synthetic profile matrix needs only the generic AMBA core,
# so apply the repository-owned compile-test patch before Kconfig evaluation.
AMBA_PATCH="$ROOT/platform/kernel/amba-compile-test.patch"

[ -f "$SRC/Makefile" ] || { echo "Linux submodule missing; run git submodule update --init"; exit 1; }
[ -f "$CONFIG" ] || { echo "Kernel config missing: $CONFIG"; exit 1; }
[ -f "$AMBA_PATCH" ] || { echo "AMBA compile-test patch missing: $AMBA_PATCH"; exit 1; }

if git -C "$SRC" apply --check "$AMBA_PATCH" >/dev/null 2>&1; then
    git -C "$SRC" apply "$AMBA_PATCH"
elif ! git -C "$SRC" apply --reverse --check "$AMBA_PATCH" >/dev/null 2>&1; then
    echo "cannot apply AMBA compile-test patch to $SRC" >&2
    exit 1
fi

mkdir -p "$OUT"
if [ ! -f "$OUT/.config" ] || ! cmp -s "$CONFIG" "$OUT/.config.seed"; then
    cp "$CONFIG" "$OUT/.config"
    cp "$CONFIG" "$OUT/.config.seed"
fi

make -C "$SRC" O="$OUT" olddefconfig

case "$MODE" in
  prepare)
    make -C "$SRC" O="$OUT" -j"$JOBS" prepare modules_prepare
    ;;
  build)
    make -C "$SRC" O="$OUT" -j"$JOBS" bzImage modules
    ;;
  *)
    echo "usage: $0 [prepare|build]"; exit 2
    ;;
esac

echo "kernel source: $SRC"
echo "kernel build:  $OUT"
make -s -C "$OUT" kernelrelease
