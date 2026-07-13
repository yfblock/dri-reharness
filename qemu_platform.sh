#!/bin/bash
# qemu_platform.sh — 用 device-registrar 注册 platform 设备, 测试合成的 platform 驱动
# 用法: qemu_platform.sh <module_name> <registrar_target> [timeout]
#   module_name: 合成驱动模块名 (如 ftgpio010_gpio), 对应 output/<module_name>/<module_name>.ko
#   registrar_target: device-registrar 注册的 platform device 名 (= 驱动 .driver.name, 如 ftgpio010-gpio)
set -u
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
KERNEL_BZIMAGE="${KERNEL_BZIMAGE:-/home/yfblock/Code/linux/arch/x86/boot/bzImage}"
KERNEL_VERSION="${KERNEL_VERSION:-7.1.0-rc7-gacb7500801e9-dirty}"
MODULE_NAME="${1:?need module_name}"
REGISTRAR_TARGET="${2:?need registrar_target}"
TIMEOUT="${3:-90}"
REGISTRAR_KO="${REGISTRAR_KO:-/home/yfblock/Code/linux-driver-harness/test/device-registrar.ko}"
OUTPUT_DIR="$PROJECT_DIR/output/$MODULE_NAME"
ROOTFS_DIR="$PROJECT_DIR/test_rootfs_plat"
INITRAMFS="$PROJECT_DIR/initramfs_plat.cpio.gz"
OUT=/tmp/reharness_qemu_plat.txt

[ -f "$OUTPUT_DIR/$MODULE_NAME.ko" ] || { echo "先编译 $MODULE_NAME"; exit 1; }
[ -f "$REGISTRAR_KO" ] || { echo "缺少 device-registrar.ko: $REGISTRAR_KO"; exit 1; }

echo "=== QEMU platform test: module=$MODULE_NAME target=$REGISTRAR_TARGET timeout=${TIMEOUT}s ==="
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
cp "$REGISTRAR_KO" "$ROOTFS_DIR/lib/modules/device-registrar.ko"
# gpio 回调 trace 测试程序 (静态, 用 v2 chardev ioctl 行使 get/set/direction)
cp "$PROJECT_DIR/test/gpio_trace_test" "$ROOTFS_DIR/bin/gpio_trace_test" 2>/dev/null && chmod +x "$ROOTFS_DIR/bin/gpio_trace_test" || true

cat > "$ROOTFS_DIR/init" <<INIT
#!/bin/sh
mount -t proc proc /proc 2>/dev/null
mount -t sysfs sysfs /sys 2>/dev/null
mount -t devtmpfs devtmpfs /dev 2>/dev/null
( sleep 15; echo o > /proc/sysrq-trigger 2>/dev/null; echo b > /proc/sysrq-trigger 2>/dev/null ) &
echo "=== insmod device-registrar target=$REGISTRAR_TARGET ==="
insmod /lib/modules/device-registrar.ko target="$REGISTRAR_TARGET" 2>&1
sleep 0.3
echo "=== insmod $MODULE_NAME ==="
insmod /lib/modules/$MODULE_NAME.ko 2>&1
sleep 0.3
echo "=== dmesg (driver+registrar) ==="
dmesg | grep -iE '$REGISTRAR_TARGET|$MODULE_NAME|ftgpio|gpiochip|probe|gpio' | tail -25
echo "=== /sys/bus/gpio/devices ==="
ls /sys/bus/gpio/devices/ 2>&1 | head
echo "=== gpio 回调 trace (get/set/direction) ==="
/bin/gpio_trace_test /dev/gpiochip0 2>&1
echo "=== rmmod $MODULE_NAME ==="
rmmod $MODULE_NAME 2>&1
rmmod device-registrar 2>/dev/null
sleep 0.2
echo "=== QEMU_PLAT_DONE ==="
echo o > /proc/sysrq-trigger 2>/dev/null
INIT
chmod +x "$ROOTFS_DIR/init"
( cd "$ROOTFS_DIR" && find . -print0 | cpio --null -o --format=newc 2>/dev/null | gzip -9 > "$INITRAMFS" )

rm -f "$OUT"
timeout --kill-after=5 "$TIMEOUT" qemu-system-x86_64 \
    -kernel "$KERNEL_BZIMAGE" -initrd "$INITRAMFS" \
    -append "console=ttyS0 nokaslr panic=1 ignore_loglevel earlyprintk=serial,ttyS0,115200" \
    -nographic -m 256M -smp 2 -no-reboot -monitor none </dev/null > "$OUT" 2>&1
RC=$?
echo "=== QEMU 退出码: $RC ==="
grep -aiE 'insmod|rmmod|device-registrar|probed|probe|gpiochip|gpio|QEMU_PLAT_DONE|/sys/bus/gpio' "$OUT" | tail -25

echo ""; echo "=== 成功判定 ==="
DONE=$(grep -ac 'QEMU_PLAT_DONE' "$OUT")
PROBE=$(grep -acE 'probed|probe.*成功|registered' "$OUT")
GPIOCHIP=$(grep -acE 'gpiochip|GPIO chip|gpiochip_add' "$OUT")
REAL_OOPS=$(grep -aE 'Oops:|BUG:|Unable to handle|general protection|Kernel panic - not syncing' "$OUT" | grep -vacE 'Attempted to kill init')
echo "  done=$DONE probe=$PROBE gpiochip=$GPIOCHIP real_oops=$REAL_OOPS"
if [ "$REAL_OOPS" -gt 0 ]; then echo "  => 失败: 崩溃/oops"; exit 2; fi
if [ "$DONE" -gt 0 ] && [ "$PROBE" -gt 0 ]; then
    echo "  => 成功: $MODULE_NAME probe platform 设备, 寄存器交互执行"
    exit 0
fi
echo "  => 失败: 未完成 probe"; exit 1
