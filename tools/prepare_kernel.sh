#!/usr/bin/env bash
# Prepare or fully build the pinned experiment kernel without dirtying linux/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${KERNEL_SOURCE:-$ROOT/linux}"
OUT="${KERNEL_BUILD_DIR:-$ROOT/kernel/build}"
CONFIG="${KERNEL_CONFIG:-$ROOT/kernel/linux-x86_64.config}"
MODE="${1:-prepare}"
JOBS="${JOBS:-$(nproc)}"

[ -f "$SRC/Makefile" ] || { echo "Linux submodule missing; run git submodule update --init"; exit 1; }
[ -f "$CONFIG" ] || { echo "Kernel config missing: $CONFIG"; exit 1; }

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
