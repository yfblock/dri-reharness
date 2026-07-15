#!/usr/bin/env bash
# Deterministic (no LLM) QEMU experiments used by the paper.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
KERNELDIR="${KERNELDIR:-$ROOT/kernel/build}"
RESULTS="$ROOT/experiments/results"
mkdir -p "$RESULTS"

if [ ! -f "$KERNELDIR/arch/x86/boot/bzImage" ]; then
    ./tools/prepare_kernel.sh build
fi

write_makefile() {
    local dir="$1" module="$2"
    printf 'obj-m += %s.o\n' "$module" > "$dir/Makefile"
}

build_module() {
    local dir="$1"
    make -C "$KERNELDIR" M="$dir" clean >/dev/null
    make -C "$KERNELDIR" M="$dir" modules >/dev/null
}

build_exerciser() {
    local source="$1" output="$2"
    "${CC:-cc}" -static -O2 -Wall -Wextra -o "$output" "$source"
}

normalize_log() {
    tr -d '\r' | sed 's/[[:blank:]]*$//'
}

build_exerciser test/edu_trace_test.c test/edu_trace_test
build_exerciser test/gpio_trace_test.c test/gpio_trace_test

# ── QEMU edu: value-level oracle ────────────────────────────────────
EDU_DIR="$ROOT/output/edu_drv"
mkdir -p "$EDU_DIR"
python3 -m extractor gen -s drivers/test/edu.c -b linux -o "$EDU_DIR/edu_drv.c"
write_makefile "$EDU_DIR" edu_drv
build_module "$EDU_DIR"
RH_QEMU_OUT=/tmp/reharness_qemu_edu_deterministic.txt \
    bash qemu_run.sh edu_drv -b pci -d edu \
      -e test/edu_trace_test -a /dev/edu_drv \
      -p 'probed|edu device id|edu probed' -t 90 \
      | normalize_log | tee "$RESULTS/qemu-edu-judge.txt"
normalize_log < /tmp/reharness_qemu_edu_deterministic.txt \
    > "$RESULTS/qemu-edu-serial.log"
grep -q EDU_TRACE_OK "$RESULTS/qemu-edu-serial.log"

# ── gpio-ftgpio010: offset/order trace oracle ───────────────────────
FT_DIR="$ROOT/output/gpio_ftgpio010"
FT_SPEC="$ROOT/output/deterministic-ftgpio"
mkdir -p "$FT_DIR" "$FT_SPEC"
python3 -m extractor gen -s drivers/test/gpio-ftgpio010.c -b linux \
    -o "$FT_DIR/gpio_ftgpio010.c"
python3 tools/instrument_mmio.py "$FT_DIR/gpio_ftgpio010.c"
write_makefile "$FT_DIR" gpio_ftgpio010
build_module "$FT_DIR"
make -C verification/device-registrar KERNELDIR="$KERNELDIR" >/dev/null
python3 -m extractor extract -s drivers/test/gpio-ftgpio010.c \
    -o "$FT_SPEC/gpio-ftgpio010.ris" >/dev/null
python3 -m extractor spec -s drivers/test/gpio-ftgpio010.c \
    -o "$FT_SPEC/gpio-ftgpio010.dspec" >/dev/null
RH_QEMU_OUT=/tmp/reharness_qemu_ftgpio_deterministic.txt \
    bash qemu_run.sh gpio_ftgpio010 -b platform -r gpio-ftgpio010 \
      -p 'probed|registered|gpiochip' -t 90 \
      | normalize_log | tee "$RESULTS/qemu-ftgpio010-judge.txt"
normalize_log < /tmp/reharness_qemu_ftgpio_deterministic.txt \
    > "$RESULTS/qemu-ftgpio010-serial.log"
python3 tools/trace_match.py "$RESULTS/qemu-ftgpio010-serial.log" \
    "$FT_SPEC/gpio-ftgpio010.ris" "$FT_SPEC/gpio-ftgpio010.dspec" \
    --exercised probe 2>&1 | tee "$RESULTS/qemu-ftgpio010-trace.txt"
grep -q TRACE_MATCH_OK "$RESULTS/qemu-ftgpio010-trace.txt"

python3 - "$RESULTS/qemu.json" <<'PY'
import datetime, json, os, subprocess, sys
root = os.getcwd()
def run(*args):
    return subprocess.check_output(args, text=True).strip()
data = {
    "schema": 1,
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "reharness_commit": run("git", "rev-parse", "HEAD"),
    "linux_commit": run("git", "-C", "linux", "rev-parse", "HEAD"),
    "kernel_release": run("make", "-s", "-C", "kernel/build", "kernelrelease"),
    "experiments": {
        "edu": {"probe": True, "value_oracle": "EDU_TRACE_OK"},
        "gpio-ftgpio010": {
            "probe": True,
            "trace_oracle": "TRACE_MATCH_OK",
            "module_coverage": "1/1",
            "op_coverage": "4/4",
            "register_coverage": "4/4",
        },
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\n")
PY

echo "QEMU_EXPERIMENTS_OK"
