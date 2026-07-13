#!/bin/bash
# qemu_run.sh — 统一 QEMU runner (替换 qemu_edu.sh + qemu_platform.sh)
# 用法: qemu_run.sh <module> [options]
#   -b/--bus platform|pci       默认 platform
#   -d/--device NAME            pci 时 -device NAME (如 edu); platform 时不用
#   -r/--registrar-target NAME  platform 时 device-registrar 注册的设备名
#   -e/--exerciser PATH         测试程序路径 (空=probe-only, 只 insmod/rmmod)
#   -a/--exerciser-args ARGS    测试程序参数 (如 /dev/gpiochip0)
#   -p/--probe-pattern PAT      probe 成功 grep 模式 (如 "probed|registered|gpiochip")
#   -t/--timeout N              默认 90
set -u
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

KERNEL_BZIMAGE="${KERNEL_BZIMAGE:-/home/yfblock/Code/linux/arch/x86/boot/bzImage}"
KERNEL_VERSION="${KERNEL_VERSION:-7.1.0-rc7-gacb7500801e9-dirty}"
REGISTRAR_KO="${REGISTRAR_KO:-/home/yfblock/Code/linux-driver-harness/test/device-registrar.ko}"
OUT="${RH_QEMU_OUT:-/tmp/reharness_qemu_run.txt}"

# 默认值
MODULE_NAME=""
BUS="platform"
QEMU_DEVICE=""
REGISTRAR_TARGET=""
EXERCISER=""
EXERCISER_ARGS=""
PROBE_PATTERN="probed|registered"
TIMEOUT=90

# 参数解析
MODULE_NAME="${1:?用法: qemu_run.sh <module> [options]}"
shift
while [ $# -gt 0 ]; do
  case "$1" in
    -b|--bus) BUS="$2"; shift 2 ;;
    -d|--device) QEMU_DEVICE="$2"; shift 2 ;;
    -r|--registrar-target) REGISTRAR_TARGET="$2"; shift 2 ;;
    -e|--exerciser) EXERCISER="$2"; shift 2 ;;
    -a|--exerciser-args) EXERCISER_ARGS="$2"; shift 2 ;;
    -p|--probe-pattern) PROBE_PATTERN="$2"; shift 2 ;;
    -t|--timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

OUTPUT_DIR="$PROJECT_DIR/output/$MODULE_NAME"
ROOTFS_DIR="$PROJECT_DIR/test_rootfs_run"
INITRAMFS="$PROJECT_DIR/initramfs_run.cpio.gz"

[ -f "$OUTPUT_DIR/$MODULE_NAME.ko" ] || { echo "先编译 $MODULE_NAME"; exit 1; }

echo "=== QEMU run: module=$MODULE_NAME bus=$BUS timeout=${TIMEOUT}s ==="

# ── 构建 rootfs (通用) ──
rm -rf "$ROOTFS_DIR"; mkdir -p "$ROOTFS_DIR"/{bin,sbin,etc,proc,sys,dev,tmp,lib/modules}
for cmd in sh ls cat echo insmod rmmod lsmod dmesg poweroff reboot mount dd head grep tail find sed sleep; do
    p=$(which $cmd 2>/dev/null || true); [ -n "$p" ] && cp "$p" "$ROOTFS_DIR/bin/" 2>/dev/null || true
done
for cmd in sh ls cat mount insmod dmesg rmmod sleep; do
    p=$(which $cmd 2>/dev/null || true); [ -n "$p" ] && ldd "$p" 2>/dev/null | grep -oP '/\S+' | while read lib; do
        [ -f "$lib" ] && { d=$(dirname "$lib"); mkdir -p "$ROOTFS_DIR$d"; cp "$lib" "$ROOTFS_DIR$lib" 2>/dev/null || true; }; done
done
mkdir -p "$ROOTFS_DIR/lib64"; cp /lib64/ld-linux-x86-64.so.2 "$ROOTFS_DIR/lib64/" 2>/dev/null || true
cp "$OUTPUT_DIR/$MODULE_NAME.ko" "$ROOTFS_DIR/lib/modules/"

# device-registrar (platform bus 需要)
if [ "$BUS" = "platform" ]; then
    [ -f "$REGISTRAR_KO" ] || { echo "缺少 device-registrar.ko: $REGISTRAR_KO"; exit 1; }
    cp "$REGISTRAR_KO" "$ROOTFS_DIR/lib/modules/device-registrar.ko"
fi

# exerciser (可选)
if [ -n "$EXERCISER" ] && [ -f "$PROJECT_DIR/$EXERCISER" ]; then
    cp "$PROJECT_DIR/$EXERCISER" "$ROOTFS_DIR/bin/exerciser" && chmod +x "$ROOTFS_DIR/bin/exerciser"
fi

# ── 动态 init 脚本 ──
cat > "$ROOTFS_DIR/init" <<INIT
#!/bin/sh
mount -t proc proc /proc 2>/dev/null
mount -t sysfs sysfs /sys 2>/dev/null
mount -t devtmpfs devtmpfs /dev 2>/dev/null
( sleep 15; echo o > /proc/sysrq-trigger 2>/dev/null; echo b > /proc/sysrq-trigger 2>/dev/null ) &
INIT

# platform: 先 insmod device-registrar
if [ "$BUS" = "platform" ]; then
    cat >> "$ROOTFS_DIR/init" <<INIT
echo "=== insmod device-registrar target=$REGISTRAR_TARGET ==="
insmod /lib/modules/device-registrar.ko target="$REGISTRAR_TARGET" 2>&1
sleep 0.3
INIT
fi

# insmod 驱动模块
cat >> "$ROOTFS_DIR/init" <<INIT
echo "=== insmod $MODULE_NAME ==="
insmod /lib/modules/$MODULE_NAME.ko 2>&1
sleep 0.3
echo "=== dmesg ==="
dmesg | grep -iE '$REGISTRAR_TARGET|$MODULE_NAME|probed|registered|probe|gpiochip|clk|ahci|mmc' | tail -25
INIT

# exerciser (如果有)
if [ -n "$EXERCISER" ]; then
    cat >> "$ROOTFS_DIR/init" <<INIT
echo "=== exerciser ==="
/bin/exerciser $EXERCISER_ARGS 2>&1
INIT
fi

# rmmod + 结束
cat >> "$ROOTFS_DIR/init" <<INIT
echo "=== rmmod $MODULE_NAME ==="
rmmod $MODULE_NAME 2>&1
rmmod device-registrar 2>/dev/null
sleep 0.2
echo "=== QEMU_RUN_DONE ==="
echo o > /proc/sysrq-trigger 2>/dev/null
INIT
chmod +x "$ROOTFS_DIR/init"
( cd "$ROOTFS_DIR" && find . -print0 | cpio --null -o --format=newc 2>/dev/null | gzip -9 > "$INITRAMFS" )

# ── 启动 QEMU ──
rm -f "$OUT"
QEMU_ARGS=(
    -kernel "$KERNEL_BZIMAGE"
    -initrd "$INITRAMFS"
    -append "console=ttyS0 nokaslr panic=1 ignore_loglevel earlyprintk=serial,ttyS0,115200"
    -nographic -m 256M -smp 2 -no-reboot -monitor none
)
if [ "$BUS" = "pci" ] && [ -n "$QEMU_DEVICE" ]; then
    QEMU_ARGS+=(-device "$QEMU_DEVICE")
fi
timeout --kill-after=5 "$TIMEOUT" qemu-system-x86_64 "${QEMU_ARGS[@]}" </dev/null > "$OUT" 2>&1
RC=$?

echo "=== QEMU 退出码: $RC ==="
grep -aiE 'insmod|rmmod|probed|registered|probe|QEMU_RUN_DONE' "$OUT" | tail -25

# ── 成功判定 (通用) ──
echo ""; echo "=== 成功判定 ==="
DONE=$(grep -ac 'QEMU_RUN_DONE' "$OUT")
PROBE=$(grep -acE "$PROBE_PATTERN" "$OUT")
REAL_OOPS=$(grep -aE 'Oops:|BUG:|Unable to handle|general protection|Kernel panic - not syncing' "$OUT" | grep -vacE 'Attempted to kill init')
echo "  done=$DONE probe=$PROBE real_oops=$REAL_OOPS"
if [ "$REAL_OOPS" -gt 0 ]; then echo "  => 失败: 崩溃/oops"; exit 2; fi
if [ "$DONE" -gt 0 ] && [ "$PROBE" -gt 0 ]; then
    echo "  => 成功: $MODULE_NAME probe 成功"
    exit 0
fi
echo "  => 失败: 未完成 probe"; exit 1
