#!/usr/bin/env python3
"""Multi-arch QEMU boot smoke (Python port of tools/guest/boot_smoke.sh).

Copies the baseline edu source (identity semantics — no LLM call), injects
[rhcov] probes, cross-compiles the module, packs a freestanding initramfs,
boots each architecture, and judges the serial log for the probe markers.

usage: boot_smoke.py x86_64|arm64|riscv64
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ARCHES = {
    "x86_64": {
        "kernel_build": "platform/kernel/build",
        "qemu": "qemu-system-x86_64",
        "machine": ["-M", "pc"],
        "console": "ttyS0", "karch": "x86_64", "cross": "",
        "image": "arch/x86/boot/bzImage",
        "hostcc": "gcc", "env": {},
    },
    "arm64": {
        "kernel_build": "platform/kernel/build-arm64",
        "qemu": "qemu-system-aarch64",
        "machine": ["-M", "virt", "-cpu", "cortex-a57"],
        "console": "ttyAMA0", "karch": "arm64",
        "cross": "aarch64-linux-gnu-",
        "image": "arch/arm64/boot/Image",
        "hostcc": "aarch64-linux-gnu-gcc", "env": {},
    },
    "riscv64": {
        "kernel_build": "platform/kernel/build-riscv64",
        "qemu": "qemu-system-riscv64",
        "machine": ["-M", "virt"],
        "console": "ttyS0", "karch": "riscv",
        "cross": "riscv64-linux-gnu-",
        "image": "arch/riscv/boot/Image",
        "hostcc": "riscv64-linux-gnu-gcc",
        "env": {
            "LD_LIBRARY_PATH": os.path.expanduser(
                "~/tc-riscv/root/usr/lib/x86_64-linux-gnu"),
            "PATH": os.path.expanduser("~/tc-riscv/root/usr/bin")
                    + os.pathsep + os.environ.get("PATH", ""),
        },
    },
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in ARCHES:
        print("usage: boot_smoke.py x86_64|arm64|riscv64", file=sys.stderr)
        return 2
    arch = argv[0]
    spec = ARCHES[arch]
    kernel_build = ROOT / spec["kernel_build"]
    work = Path(f"/tmp/qemu-smoke-{arch}")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    shutil.copy2(ROOT / "benchmarks/drivers/baseline/edu.c", work / "edu.c")
    subprocess.run(
        [sys.executable,
         str(ROOT / "tools/source/inject_function_coverage.py"),
         str(work / "edu.c"),
         "--inventory-output", str(work / "edu.rhcov.json"),
         "--in-place"], check=True, cwd=ROOT)
    (work / "Makefile").write_text("obj-m += edu.o\n")
    make = ["make", "-C", str(kernel_build), "ARCH=" + spec["karch"]]
    if spec["cross"]:
        make.append("CROSS_COMPILE=" + spec["cross"])
    make += [f"M={work.resolve()}", "modules"]
    subprocess.run(make, cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    if not (work / "edu.ko").is_file():
        print(f"{arch}: module build failed", file=sys.stderr)
        return 1

    env = {**os.environ, **spec["env"]}
    subprocess.run(
        [spec["hostcc"], "-nostdlib", "-static", "-o", str(work / "init"),
         str(ROOT / "tools/guest/reharness_init.c")], check=True, env=env)
    cpio_list = work / "list"
    cpio_list.write_text(
        "dir /proc 0755 0 0\n"
        "dir /sys 0755 0 0\n"
        "dir /dev 0755 0 0\n"
        "nod /dev/console 0600 0 0 c 5 1\n"
        f"file /init {work}/init 0755 0 0\n"
        f"file /edu.ko {work}/edu.ko 0644 0 0\n")
    with (work / "initramfs.cpio").open("wb") as handle:
        gen = subprocess.run(
            [str(kernel_build / "usr/gen_init_cpio"), str(cpio_list)],
            capture_output=True, check=True)
        handle.write(gen.stdout)

    serial = work / "serial.log"
    subprocess.run(
        ["timeout", "120", spec["qemu"], *spec["machine"],
         "-m", "512M", "-kernel", str(kernel_build / spec["image"]),
         "-initrd", str(work / "initramfs.cpio"),
         "-append", f"console={spec['console']} ignore_loglevel",
         "-nographic", "-device", "edu"],
        stdin=subprocess.DEVNULL, stdout=serial.open("wb"),
        stderr=subprocess.STDOUT, env=env)

    log = serial.read_text(errors="replace")
    markers = [line for line in log.splitlines()
               if any(key in line for key in
                      ("REHARNESS_MODULE_LOAD", "REHARNESS_EXPECT_FOUND",
                       "[rhcov] edu_probe"))]
    print(f"== {arch} 结果 ==")
    for line in markers:
        print(line)
    if ("REHARNESS_EXPECT_FOUND=1" in log and "[rhcov] edu_probe" in log):
        print(f"SMOKE {arch}: PASS")
        return 0
    print("（未找到判定标记——串口尾部：）")
    for line in log.splitlines()[-12:]:
        print(line)
    print(f"SMOKE {arch}: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
