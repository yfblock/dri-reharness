#!/usr/bin/env bash
# Build the pinned vendor/linux kernel for a chosen architecture.
#   usage: prepare_kernel_multiarch.sh x86_64|arm64|riscv64 [build]
# Outputs: platform/kernel/build[-arm64|-riscv64] (+ kernel image / Module.symvers)
set -euo pipefail

ARCH="${1:?usage: $0 x86_64|arm64|riscv64 [build]}"
MODE="${2:-build}"
JOBS="${JOBS:-$(nproc)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
SRC="${KERNEL_SOURCE:-$ROOT/vendor/linux}"
AMBA_PATCH="$ROOT/platform/kernel/amba-compile-test.patch"

case "$ARCH" in
  x86_64)
    OUT="${KERNEL_BUILD_DIR:-$ROOT/platform/kernel/build}"
    CONFIG="$ROOT/platform/kernel/linux-x86_64.config"
    KCPU=(); TARGET="bzImage modules"
    ;;
  arm64)
    OUT="${KERNEL_BUILD_DIR:-$ROOT/platform/kernel/build-arm64}"
    CONFIG="$ROOT/platform/kernel/linux-arm64.fragment"
    KCPU=(ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-)
    TARGET="Image modules"
    ;;
  riscv64)
    OUT="${KERNEL_BUILD_DIR:-$ROOT/platform/kernel/build-riscv64}"
    CONFIG="$ROOT/platform/kernel/linux-riscv64.fragment"
    KCPU=(ARCH=riscv CROSS_COMPILE=riscv64-linux-gnu-)
    TARGET="Image modules"
    export LD_LIBRARY_PATH="$HOME/tc-riscv/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export PATH="$HOME/tc-riscv/root/usr/bin:$PATH"
    ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 2 ;;
esac

[ -f "$SRC/Makefile" ] || { echo "Linux submodule missing" >&2; exit 1; }

if git -C "$SRC" apply --check "$AMBA_PATCH" >/dev/null 2>&1; then
    git -C "$SRC" apply "$AMBA_PATCH"
elif ! git -C "$SRC" apply --reverse --check "$AMBA_PATCH" >/dev/null 2>&1; then
    echo "cannot apply AMBA compile-test patch to $SRC" >&2
    exit 1
fi

mkdir -p "$OUT"
if [ "$ARCH" = "x86_64" ]; then
    [ -f "$CONFIG" ] || { echo "config missing: $CONFIG" >&2; exit 1; }
    if [ ! -f "$OUT/.config" ] || ! cmp -s "$CONFIG" "$OUT/.config.seed"; then
        cp "$CONFIG" "$OUT/.config"
        cp "$CONFIG" "$OUT/.config.seed"
    fi
    make -C "$SRC" O="$OUT" "${KCPU[@]}" olddefconfig
else
    make -C "$SRC" O="$OUT" "${KCPU[@]}" defconfig
    # 平台碎片：PCI(edu 设备宿主) + 串口控制台 + devtmpfs + 模块支持
    "$SRC/scripts/config" --file "$OUT/.config" \
        -e PCI -e PCI_HOST_GENERIC \
        -e DEVTMPFS -e DEVTMPFS_MOUNT \
        -e MODULES
    case "$ARCH" in
        arm64)
            "$SRC/scripts/config" --file "$OUT/.config" \
                -e SERIAL_AMBA_PL011 -e SERIAL_AMBA_PL011_CONSOLE ;;
        riscv64)
            "$SRC/scripts/config" --file "$OUT/.config" \
                -e SERIAL_8250 -e SERIAL_8250_CONSOLE ;;
    esac
    make -C "$SRC" O="$OUT" "${KCPU[@]}" olddefconfig
fi

make -C "$SRC" O="$OUT" -j"$JOBS" ${KCPU[@]} $TARGET

echo "kernel source: $SRC"
echo "kernel build:  $OUT ($ARCH)"
make -s -C "$OUT" "${KCPU[@]}" kernelrelease
