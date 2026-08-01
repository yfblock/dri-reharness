#!/bin/bash
# qemu_run.sh — manifest-configured QEMU runner
# 用法: qemu_run.sh <module> [options]
#   -b/--bus platform|pci       默认 platform
#   -d/--device NAME            pci 时传给 QEMU 的 device model
#   -r/--registrar-target NAME  platform 时 device-registrar 注册的设备名
#   -e/--exerciser PATH         测试程序路径 (空=probe-only, 只 insmod/rmmod)
#   -a/--exerciser-args ARGS    测试程序参数
#   -s/--success-pattern REGEX   exerciser success marker supplied by manifest
#   -p/--probe-pattern PAT      probe 成功 grep 模式
#   -m/--machine NAME           QEMU machine model
#   --manifest PATH             load all runtime/test policy from manifest
#   -t/--timeout N              默认 90
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$PROJECT_DIR"

KERNELDIR="${KERNELDIR:-$PROJECT_DIR/platform/kernel/build}"
KERNEL_BZIMAGE="${KERNEL_BZIMAGE:-$KERNELDIR/arch/x86/boot/bzImage}"
KERNEL_VERSION="${KERNEL_VERSION:-$(make -s -C "$KERNELDIR" kernelrelease 2>/dev/null || true)}"
REGISTRAR_KO="${REGISTRAR_KO:-$PROJECT_DIR/qa/verification/device-registrar/device-registrar.ko}"

# 默认值
MODULE_NAME=""
MANIFEST=""
BUS="platform"
MACHINE="q35"
QEMU_DEVICE=""
REGISTRAR_TARGET=""
EXERCISER=""
EXERCISER_ARGS=""
PROBE_PATTERN="probed|registered"
SUCCESS_PATTERN=""
TIMEOUT=90
QEMU_EXTRA_ARGS=()

# 参数解析
if [ "${1:-}" = "--manifest" ]; then
    MANIFEST="${2:?--manifest requires a path}"
    shift 2
else
    MODULE_NAME="${1:?用法: qemu_run.sh <module> [options]}"
    shift
fi
while [ $# -gt 0 ]; do
  case "$1" in
    -b|--bus) BUS="$2"; shift 2 ;;
    -m|--machine) MACHINE="$2"; shift 2 ;;
    -d|--device) QEMU_DEVICE="$2"; shift 2 ;;
    -r|--registrar-target) REGISTRAR_TARGET="$2"; shift 2 ;;
    -e|--exerciser) EXERCISER="$2"; shift 2 ;;
    -a|--exerciser-args) EXERCISER_ARGS="$2"; shift 2 ;;
    -s|--success-pattern) SUCCESS_PATTERN="$2"; shift 2 ;;
    --qemu-arg) QEMU_EXTRA_ARGS+=("$2"); shift 2 ;;
    -p|--probe-pattern) PROBE_PATTERN="$2"; shift 2 ;;
    -t|--timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [ -n "$MANIFEST" ]; then
    eval "$(python3 - "$MANIFEST" <<'PY'
import shlex, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from experiment_manifest import load_manifest
m = load_manifest(sys.argv[1], repo_root=Path.cwd())
q = m.runtime.qemu
def emit(name, value):
    print(f"{name}={shlex.quote(str(value))}")
emit("MODULE_NAME", q.module)
emit("BUS", q.bus)
emit("MACHINE", q.machine)
emit("QEMU_DEVICE", q.device)
emit("TIMEOUT", q.timeout_seconds)
emit("PROBE_PATTERN", q.probe_pattern or "probe|registered")
emit("REGISTRAR_TARGET", q.registrar or "")
emit("EXERCISER", str(m.test.executable.relative_to(Path.cwd())))
emit("EXERCISER_ARGS", " ".join(m.test.args))
emit("SUCCESS_PATTERN", m.test.success_pattern or "")
print("QEMU_EXTRA_ARGS=(" + " ".join(shlex.quote(item) for item in q.qemu_args) + ")")
PY
)"
fi

# Every invocation gets an isolated rootfs, initramfs, and default log. This
# keeps concurrent experiments from deleting or replacing each other's state.
TMP_BASE="${RH_QEMU_TMPDIR:-${TMPDIR:-/tmp}}"
mkdir -p "$TMP_BASE"
RUN_LABEL="${RH_QEMU_RUN_ID:-${MODULE_NAME:-manifest}}"
RUN_LABEL="$(printf '%s' "$RUN_LABEL" | tr -c '[:alnum:]_.-' '_')"
RUN_DIR="$(mktemp -d "$TMP_BASE/reharness-qemu-${RUN_LABEL}.XXXXXX")" || {
    echo "无法创建 QEMU 临时运行目录: $TMP_BASE" >&2
    exit 1
}
KEEP_RUNTIME="${RH_QEMU_KEEP_RUNTIME:-0}"
cleanup_runtime() {
    rc=$?
    if [ "$KEEP_RUNTIME" != "1" ]; then
        rm -rf -- "$RUN_DIR"
    else
        echo "QEMU runtime artifacts: $RUN_DIR"
    fi
    exit "$rc"
}
trap cleanup_runtime EXIT

if [ -n "${RH_QEMU_OUT:-}" ]; then
    OUT="$RH_QEMU_OUT"
else
    OUT="$RUN_DIR/qemu.log"
fi
mkdir -p "$(dirname "$OUT")"

OUTPUT_DIR="$PROJECT_DIR/artifacts/output/$MODULE_NAME"
ROOTFS_DIR="$RUN_DIR/rootfs"
INITRAMFS="$RUN_DIR/initramfs.cpio.gz"

[ -f "$OUTPUT_DIR/$MODULE_NAME.ko" ] || { echo "先编译 $MODULE_NAME"; exit 1; }
mkdir -p "$(dirname "$INITRAMFS")"

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
PATTERN="$PROBE_PATTERN|$REGISTRAR_TARGET|$MODULE_NAME"
dmesg | grep -iE "\$PATTERN" | tail -25
INIT

# exerciser (如果有)
if [ -n "$EXERCISER" ]; then
    cat >> "$ROOTFS_DIR/init" <<INIT
echo "=== exerciser ==="
/bin/exerciser $EXERCISER_ARGS 2>&1
echo "EXERCISER_RC=\$?"
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
    -M "$MACHINE"
    -append "console=ttyS0 nokaslr panic=1 ignore_loglevel earlyprintk=serial,ttyS0,115200"
    -nographic -m 256M -smp 2 -no-reboot -monitor none
)
if [ "${#QEMU_EXTRA_ARGS[@]}" -gt 0 ]; then
    QEMU_ARGS+=("${QEMU_EXTRA_ARGS[@]}")
fi
if [ "$BUS" = "pci" ] && [ -n "$QEMU_DEVICE" ]; then
    QEMU_ARGS+=(-device "$QEMU_DEVICE")
fi
timeout --kill-after=5 "$TIMEOUT" qemu-system-x86_64 "${QEMU_ARGS[@]}" </dev/null > "$OUT" 2>&1
RC=$?

echo "=== QEMU 退出码: $RC ==="
grep -aiE 'insmod|rmmod|probed|registered|probe|TRACE|EXERCISER_RC|QEMU_RUN_DONE' "$OUT" | tail -30

# ── 成功判定 (通用) ──
echo ""; echo "=== 成功判定 ==="
DONE=$(grep -ac 'QEMU_RUN_DONE' "$OUT")
PROBE=$(grep -acE "$PROBE_PATTERN" "$OUT")
REAL_OOPS=$(grep -aE 'Oops:|BUG:|Unable to handle|general protection|Kernel panic - not syncing' "$OUT" | grep -vacE 'Attempted to kill init')
EX_RC_OK=1
if [ -n "$EXERCISER" ]; then
    grep -aq 'EXERCISER_RC=0' "$OUT" || EX_RC_OK=0
fi
if [ -n "$SUCCESS_PATTERN" ]; then
    grep -aqE "$SUCCESS_PATTERN" "$OUT" || EX_RC_OK=0
fi
echo "  done=$DONE probe=$PROBE real_oops=$REAL_OOPS"
if [ "$REAL_OOPS" -gt 0 ]; then echo "  => 失败: 崩溃/oops"; exit 2; fi
if [ "$DONE" -gt 0 ] && [ "$PROBE" -gt 0 ] && [ "$EX_RC_OK" -eq 1 ]; then
    echo "  => 成功: $MODULE_NAME probe 成功"
    exit 0
fi
if [ "$EX_RC_OK" -ne 1 ]; then echo "  => 失败: exerciser/语义检查未通过"; exit 3; fi
echo "  => 失败: 未完成 probe"; exit 1
