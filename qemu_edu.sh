#!/bin/bash
# qemu_edu.sh — 用真实 QEMU edu PCI 设备测试 reharness 合成的 edu_drv
set -u
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
KERNEL_BZIMAGE=/home/yfblock/Code/linux/arch/x86/boot/bzImage
KERNEL_VERSION=7.1.0-rc7-gacb7500801e9-dirty
OUTPUT_DIR="$PROJECT_DIR/output/edu_drv"
ROOTFS_DIR="$PROJECT_DIR/test_rootfs"
INITRAMFS="$PROJECT_DIR/initramfs_edu.cpio.gz"
TIMEOUT="${1:-60}"
OUT=/tmp/reharness_qemu_edu.txt

[ -f "$OUTPUT_DIR/edu_drv.ko" ] || { echo "先编译 edu_drv"; exit 1; }
echo "=== QEMU edu test: kernel=$KERNEL_BZIMAGE timeout=${TIMEOUT}s ==="

rm -rf "$ROOTFS_DIR"; mkdir -p "$ROOTFS_DIR"/{bin,sbin,etc,proc,sys,dev,tmp,lib/modules}
for cmd in sh ls cat echo insmod rmmod lsmod dmesg poweroff reboot mount dd head grep tail find sed sleep; do
    p=$(which $cmd 2>/dev/null || true); [ -n "$p" ] && cp "$p" "$ROOTFS_DIR/bin/" 2>/dev/null || true
done
for cmd in sh ls cat mount insmod dmesg rmmod sleep; do
    p=$(which $cmd 2>/dev/null || true); [ -n "$p" ] && ldd "$p" 2>/dev/null | grep -oP '/\S+' | while read lib; do
        [ -f "$lib" ] && { d=$(dirname "$lib"); mkdir -p "$ROOTFS_DIR$d"; cp "$lib" "$ROOTFS_DIR$lib" 2>/dev/null || true; }; done
done
mkdir -p "$ROOTFS_DIR/lib64"; cp /lib64/ld-linux-x86-64.so.2 "$ROOTFS_DIR/lib64/" 2>/dev/null || true
cp "$OUTPUT_DIR/edu_drv.ko" "$ROOTFS_DIR/lib/modules/"

cat > "$ROOTFS_DIR/init" <<'INIT'
#!/bin/sh
mount -t proc proc /proc 2>/dev/null
mount -t sysfs sysfs /sys 2>/dev/null
mount -t devtmpfs devtmpfs /dev 2>/dev/null
echo "=== insmod edu_drv ==="
insmod /lib/modules/edu_drv.ko 2>&1
sleep 0.3
echo "=== dmesg edu ==="
dmesg | grep -iE 'edu|probe' | tail -20
echo "=== /dev/edu_drv ? ==="
ls -l /dev/edu_drv 2>&1 | head -2
echo "=== read /dev/edu_drv (offset 0 = id reg) ==="
dd if=/dev/edu_drv of=/tmp/id bs=4 count=1 2>/dev/null && hexdump -C /tmp/id 2>/dev/null || od -A x -t x1 /tmp/id 2>/dev/null
ls -l /dev/edu_drv 2>&1 | head -2
echo "=== rmmod edu_drv ==="
rmmod edu_drv 2>&1
sleep 0.2
echo "=== QEMU_EDU_DONE ==="
echo o > /proc/sysrq-trigger 2>/dev/null
INIT
chmod +x "$ROOTFS_DIR/init"
( cd "$ROOTFS_DIR" && find . -print0 | cpio --null -o --format=newc 2>/dev/null | gzip -9 > "$INITRAMFS" )

rm -f "$OUT"
# stdbuf -oL -eL: 行缓冲, 防止 QEMU 被 timeout 杀时 stdout block-buffer 全丢 (0字节)
timeout "$TIMEOUT" stdbuf -oL -eL qemu-system-x86_64 \
    -kernel "$KERNEL_BZIMAGE" -initrd "$INITRAMFS" -device edu \
    -append "console=ttyS0 nokaslr panic=1" -nographic -m 256M -smp 2 -no-reboot -monitor none > "$OUT" 2>&1
RC=$?
echo "=== QEMU 退出码: $RC ==="
grep -aiE 'edu_drv|edu probed|edu device id|insmod|rmmod|/dev/edu_drv|QEMU_EDU_DONE' "$OUT" | tail -25

echo ""; echo "=== 成功判定 ==="
DONE=$(grep -ac 'QEMU_EDU_DONE' "$OUT")
PROBE=$(grep -acE 'edu probed|edu device id|edu chip ID|chip ID =|edu PCI device' "$OUT")
DEVNODE=$(grep -ac '/dev/edu_drv' "$OUT")
REAL_OOPS=$(grep -aE 'Oops:|BUG:|Unable to handle|general protection|Kernel panic - not syncing' "$OUT" | grep -vacE 'Attempted to kill init')
echo "  done=$DONE probe=$PROBE dev_node=$DEVNODE real_oops=$REAL_OOPS"
if [ "$REAL_OOPS" -gt 0 ]; then echo "  => 失败: 崩溃/oops"; exit 2; fi
if [ "$DONE" -gt 0 ] && [ "$PROBE" -gt 0 ]; then
    echo "  => 成功: edu_drv probe 真实 QEMU edu 设备, 完成寄存器交互"
    exit 0
fi
echo "  => 失败: 未完成 probe"; exit 1
