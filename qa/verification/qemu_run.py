#!/usr/bin/env python3
"""QEMU guest runner (Python; replaced the retired shell runner).

Boots an isolated initramfs guest per invocation: stages the module and
its dependencies, generates the guest ``init`` script (insmod → binding
wait → dmesg → exerciser → llm-tests → subsystem tests → rmmod →
``QEMU_RUN_DONE``), assembles the QEMU command line in Python, runs the
guest under a timeout, and judges the serial log.

Runtime fixtures are pluggable: each fixture kind contributes host-side
preparation (e.g. backing files) through ``FIXTURE_PLUGINS``.

Serial marker protocol and exit codes are preserved so judges and
evidence consumers are unchanged:
0 success · 1 probe not finished · 2 kernel oops/warning ·
3 exerciser/subsystem failure · 4 inconclusive.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
KERNELDIR = ROOT / "platform/kernel/build"
KERNEL_BZIMAGE = KERNELDIR / "arch/x86_64/boot/bzImage"

# ── fixture plugins ─────────────────────────────────────────────────────


class FixtureContext:
    """Inputs a fixture plugin may act on."""

    def __init__(self, config: dict[str, Any], run_dir: Path) -> None:
        self.config = config
        self.run_dir = run_dir


class FixturePlugin:
    """Host-side preparation for one runtime fixture kind."""

    kind: str = ""

    def prepare(self, ctx: FixtureContext) -> list[str]:
        """Prepare host resources; return extra QEMU arguments."""
        return []


class UsbStoragePlugin(FixturePlugin):
    kind = "qemu-usb-storage"

    def prepare(self, ctx: FixtureContext) -> list[str]:
        backing = ctx.config.get("backing_file")
        if backing:
            path = Path(backing)
            if not path.is_absolute():
                path = ROOT / path
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["truncate", "-s", str(ctx.config.get("backing_size", "64M")),
                     str(path)], check=True)
        return []


class VirtioBlkPlugin(FixturePlugin):
    kind = "qemu-virtio-blk"

    def prepare(self, ctx: FixtureContext) -> list[str]:
        backing = ctx.config.get("backing_file")
        if backing:
            path = Path(backing)
            if not path.is_absolute():
                path = ROOT / path
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["truncate", "-s", str(ctx.config.get("backing_size", "64M")),
                     str(path)], check=True)
        return []


FIXTURE_PLUGINS: dict[str, type[FixturePlugin]] = {
    plugin.kind: plugin for plugin in (UsbStoragePlugin, VirtioBlkPlugin)
}


# ── manifest spec ───────────────────────────────────────────────────────


class GuestSpec:
    """Everything the guest run needs, normalised from manifest + CLI."""

    def __init__(self, manifest: Any) -> None:
        qemu = manifest.runtime.qemu
        fixture = manifest.runtime.fixture
        test = manifest.test
        self.module: str = qemu.module
        self.bus: str = qemu.bus
        self.machine: str = qemu.machine
        self.device: str = qemu.device
        self.launch_device: bool = qemu.launch_device
        self.timeout: int = qemu.timeout_seconds
        self.probe_pattern: str = qemu.probe_pattern or "probe|registered"
        self.registrar: str = qemu.registrar or ""
        binding = qemu.binding
        self.binding_bus: str = binding.bus if binding is not None else ""
        self.binding_glob: str = (
            binding.device_glob if binding is not None else "*")
        self.binding_required: bool = (
            binding is not None and binding.required)
        self.qemu_args: list[str] = list(qemu.qemu_args)
        self.kernel_modules: list[str] = list(dict.fromkeys(
            [*qemu.kernel_modules,
             *(fixture.kernel_modules if fixture is not None else ())]))
        self.exerciser: str = (
            str(test.executable.relative_to(ROOT))
            if test.executable is not None else "")
        self.exerciser_args: str = " ".join(test.args)
        self.success_pattern: str = test.success_pattern or ""
        subsystem = test.subsystem
        self.subtests: list[Any] = (
            list(subsystem.tests) if subsystem is not None else [])
        self.coverage_required: list[str] = (
            list(test.coverage.required) if test.coverage is not None else [])
        self.fixture = fixture


def _load_manifest(manifest_path: Path) -> Any:
    sys.path.insert(0, str(ROOT / "src"))
    from experiment_manifest import load_manifest
    return load_manifest(manifest_path, repo_root=ROOT)


# ── guest build ─────────────────────────────────────────────────────────


_ROOTFS_TOOLS = (
    "sh ls cat echo insmod rmmod lsmod dmesg poweroff reboot mount dd head "
    "grep tail find sed sleep readlink ip ethtool mktemp cut id rm mkdir")


def _build_rootfs(rootfs: Path, spec: GuestSpec, module_ko: Path,
                  extra_tests: Path | None) -> None:
    for sub in ("bin", "sbin", "etc", "proc", "sys", "dev", "tmp",
                "lib/modules"):
        (rootfs / sub).mkdir(parents=True, exist_ok=True)
    for name in _ROOTFS_TOOLS.split():
        source = shutil.which(name)
        if source:
            destination = rootfs / "bin" / name
            shutil.copy2(source, destination)
            # cp(1) 语义: 非 root 拷贝时 setuid/setgid 位被清除;
            # setuid 位会让 guest 内的 mount(2) 以异常路径失败。
            destination.chmod(destination.stat().st_mode & ~0o6000)
    for name in ("sh", "ls", "cat", "mount", "insmod", "dmesg", "rmmod",
                 "sleep", "readlink", "ip", "ethtool", "mktemp", "cut",
                 "id", "rm", "mkdir"):
        source = shutil.which(name)
        if not source:
            continue
        libraries = subprocess.run(
            ["ldd", source], capture_output=True, text=True).stdout
        for library in re.findall(r"/\S+", libraries):
            library_path = Path(library)
            if library_path.is_file():
                destination = rootfs / library_path.relative_to("/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(library_path, destination)
    dynamic_loader = Path("/lib64/ld-linux-x86-64.so.2")
    if dynamic_loader.is_file():
        (rootfs / "lib64").mkdir(exist_ok=True)
        shutil.copy2(dynamic_loader, rootfs / "lib64" / dynamic_loader.name)
    shutil.copy2(module_ko, rootfs / "lib" / "modules" / f"{spec.module}.ko")

    if spec.exerciser:
        source = ROOT / spec.exerciser
        if source.is_file():
            shutil.copy2(source, rootfs / "bin" / "exerciser")
            (rootfs / "bin" / "exerciser").chmod(0o755)
    if extra_tests is not None and Path(extra_tests).is_file():
        shutil.copy2(extra_tests, rootfs / "bin" / "llm-tests")
        (rootfs / "bin" / "llm-tests").chmod(0o755)
    for staged in rootfs.glob("bin/*"):
        staged.chmod(staged.stat().st_mode & ~0o6000)

    for index, item in enumerate(spec.subtests):
        if item.kind == "kunit":
            continue
        target = rootfs / "bin" / f"reharness-subsystem-test-{index}"
        source = item.executable
        assert source is not None
        source = Path(source) if source.is_absolute() else ROOT / source
        if not source.is_file():
            raise SystemExit(
                f"REHARNESS_SUBSYSTEM_TEST_{index}_ASSET_AVAILABLE=0:{source}")
        if source.suffix == ".c":
            subprocess.run(
                ["cc", "-static", "-O2", "-Wall", "-Wextra",
                 "-o", str(target), str(source)], check=True)
        else:
            shutil.copy2(source, target)
            target.chmod(0o755)
        for asset in item.assets:
            asset_path = asset if asset.is_absolute() else ROOT / asset
            if not asset_path.is_file():
                raise SystemExit(
                    f"REHARNESS_SUBSYSTEM_TEST_{index}_ASSET_AVAILABLE=0"
                    f":{asset_path}")
            shutil.copy2(asset_path, rootfs / "bin" / asset.name)


def _stage_kernel_modules(rootfs: Path, spec: GuestSpec) -> None:
    modules = rootfs / "lib" / "modules"
    for module in spec.kernel_modules:
        hits = [p for p in KERNELDIR.rglob(f"{module}.ko")]
        if not hits:
            print(f"REHARNESS_KERNEL_MODULE_{module}_AVAILABLE=0")
            raise SystemExit(4)
        shutil.copy2(sorted(hits)[0], modules / f"{module}.ko")


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _fixture_module_build(rootfs: Path, spec: GuestSpec) -> list[str]:
    """Compile declared runtime fixture modules; return their names."""
    fixture = spec.fixture
    if fixture is None:
        return []
    names: list[str] = []
    build_root = rootfs.parent / "fixture-build"
    for source_path in fixture.module_sources:
        source = ROOT / source_path
        if not source.is_file():
            print(f"REHARNESS_RUNTIME_FIXTURE_MODULE_AVAILABLE=0:{source}")
            raise SystemExit(4)
        module = source.stem
        build_dir = build_root / module
        build_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, build_dir / f"{module}.c")
        (build_dir / "Makefile").write_text(f"obj-m += {module}.o\n")
        subprocess.run(
            ["make", "-C", str(KERNELDIR), f"M={build_dir.resolve()}", "modules"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.copy2(build_dir / f"{module}.ko",
                     rootfs / "lib" / "modules" / f"{module}.ko")
        names.append(module)
    return names


def _fixture_assets(rootfs: Path, spec: GuestSpec) -> None:
    fixture = spec.fixture
    if fixture is None:
        return
    target_dir = rootfs / "lib" / "reharness-fixture"
    target_dir.mkdir(parents=True, exist_ok=True)
    for asset in fixture.assets:
        source = asset if asset.is_absolute() else ROOT / asset
        if not source.is_file():
            print(f"REHARNESS_RUNTIME_FIXTURE_ASSET_AVAILABLE=0:{source}")
            raise SystemExit(4)
        shutil.copy2(source, target_dir / source.name)


def _build_init(rootfs: Path, spec: GuestSpec, fixture_modules: list[str]) -> None:
    lines = [
        "#!/bin/sh",
        "mount -t proc proc /proc 2>/dev/null",
        "mount -t sysfs sysfs /sys 2>/dev/null",
        "mount -t devtmpfs devtmpfs /dev 2>/dev/null",
        "mkdir -p /sys/kernel/config",
        "mount -t configfs configfs /sys/kernel/config 2>/dev/null",
        "( sleep 15; echo o > /proc/sysrq-trigger 2>/dev/null; "
        "echo b > /proc/sysrq-trigger 2>/dev/null ) &",
    ]
    fixture = spec.fixture
    if fixture is not None:
        lines += list(fixture.init_commands)
    for index, module in enumerate(spec.kernel_modules):
        lines += [
            f'echo "=== insmod required kernel module {module} ==="',
            f"insmod /lib/modules/{module}.ko 2>&1",
            "KERNEL_MODULE_INSMOD_RC=$?",
            f"echo REHARNESS_KERNEL_MODULE_{index}_NAME={module}",
            "echo REHARNESS_KERNEL_MODULE_${index}_INSMOD_RC=$KERNEL_MODULE_INSMOD_RC"
            .replace("${index}", str(index)),
        ]
    fixture_args: dict[str, Any] = (
        fixture.config.get("module_args", {}) if fixture is not None else {})
    for index, module in enumerate(fixture_modules):
        args = shlex.join(fixture_args.get(module, []))
        lines += [
            f'echo "=== insmod runtime fixture {module} ==="',
            f"insmod /lib/modules/{module}.ko {args} 2>&1",
            "FIXTURE_MODULE_INSMOD_RC=$?",
            f"echo REHARNESS_RUNTIME_FIXTURE_MODULE_{index}_INSMOD_RC"
            "=$FIXTURE_MODULE_INSMOD_RC",
        ]
    lines += [
        f'echo "=== insmod {spec.module} ==="',
        f"insmod /lib/modules/{spec.module}.ko 2>&1",
        "DRIVER_INSMOD_RC=$?",
        "echo REHARNESS_DRIVER_INSMOD_RC=$DRIVER_INSMOD_RC",
    ]
    if spec.binding_bus:
        lines += [
            "REHARNESS_DRIVER_PROBE_BOUND=0",
            "probe_attempt=0",
            'while [ "$probe_attempt" -lt 50 ]; do',
            "    REHARNESS_DRIVER_PROBE_BOUND=0",
            f"    for device in /sys/bus/{spec.binding_bus}/devices/"
            f"{spec.binding_glob}; do",
            '        [ -e "$device" ] || continue',
            '        if [ -L "$device/driver" ]; then',
            '            driver_module_path=$(readlink "$device/driver/module" '
            "2>/dev/null || true)",
            "            driver_module=${driver_module_path##*/}",
            '            if [ -z "$driver_module" ]; then',
            '                driver_path=$(readlink "$device/driver" '
            "2>/dev/null || true)",
            "                driver_module=${driver_path##*/}",
            "            fi",
            "        else",
            '            driver_module=""',
            "        fi",
            f'        if [ "$driver_module" = "{spec.module}" ]; then',
            "            REHARNESS_DRIVER_PROBE_BOUND=1",
            "            break",
            "        fi",
            "    done",
            '    [ "$REHARNESS_DRIVER_PROBE_BOUND" -eq 1 ] && break',
            "    probe_attempt=$(($probe_attempt + 1))",
            "    sleep 0.1",
            "done",
        ]
        if spec.binding_required:
            lines.append("echo REHARNESS_DRIVER_PROBE_BOUND="
                         "$REHARNESS_DRIVER_PROBE_BOUND")
    pattern = spec.probe_pattern
    if spec.registrar:
        pattern += f"|{spec.registrar}"
    pattern += f"|{spec.module}"
    lines += [
        'echo "=== dmesg ==="',
        f"dmesg | grep -iE {_shell_quote(pattern)} | tail -25",
    ]
    if spec.exerciser:
        lines += [
            'echo "=== exerciser ==="',
            f"/bin/exerciser {spec.exerciser_args} 2>&1",
            "echo EXERCISER_RC=$?",
        ]
    if (rootfs / "bin" / "llm-tests").is_file():
        lines += [
            'echo "=== llm-tests ==="',
            "/bin/llm-tests 2>&1",
            "echo LLM_TESTS_RC=$?",
        ]
    for index, item in enumerate(spec.subtests):
        if item.kind == "kunit":
            command = "dmesg"
        else:
            executable = Path(f"/bin/reharness-subsystem-test-{index}")
            command = shlex.join([str(executable), *item.args])
        lines += [
            f'echo "=== Linux subsystem test {index} ==="',
            f"eval {_shell_quote(command)} 2>&1",
            "SUBSYSTEM_TEST_RC=$?",
        ]
        if item.kind == "kunit":
            lines += [
                "if dmesg | grep -qE "
                "'(^|[[:space:]])not ok [0-9]+([[:space:]-]|$)'; then",
                "    SUBSYSTEM_TEST_RC=1",
                "fi",
            ]
        lines += [
            "SUBSYSTEM_TEST_STATUS=pass",
            'if [ "$SUBSYSTEM_TEST_RC" -eq 4 ]; then',
            "    SUBSYSTEM_TEST_STATUS=skip",
            'elif [ "$SUBSYSTEM_TEST_RC" -ne 0 ]; then',
            "    SUBSYSTEM_TEST_STATUS=fail",
            "fi",
            f"printf 'REHARNESS_SUBSYSTEM_TEST_{index}_NAME=%s\\n' "
            f"{_shell_quote(item.name)}",
            f"printf 'REHARNESS_SUBSYSTEM_TEST_{index}_KIND=%s\\n' "
            f"{_shell_quote(item.kind)}",
            f"printf 'REHARNESS_SUBSYSTEM_TEST_{index}_PROVIDER=%s\\n' "
            f"{_shell_quote(item.provider or '')}",
            f"printf 'REHARNESS_SUBSYSTEM_TEST_{index}_REQUIRED=%s\\n' "
            f"{'1' if item.required else '0'}",
            "printf 'REHARNESS_SUBSYSTEM_TEST_"
            f"{index}_RC=%s\\n' \"$SUBSYSTEM_TEST_RC\"",
            "printf 'REHARNESS_SUBSYSTEM_TEST_"
            f"{index}_STATUS=%s\\n' \"$SUBSYSTEM_TEST_STATUS\"",
        ]
    lines += [
        f'echo "=== rmmod {spec.module} ==="',
        f"rmmod {spec.module} 2>&1",
        "DRIVER_RMMOD_RC=$?",
        "echo REHARNESS_DRIVER_RMMOD_RC=$DRIVER_RMMOD_RC",
    ]
    for index in range(len(fixture_modules) - 1, -1, -1):
        module = fixture_modules[index]
        lines += [
            f"rmmod {module} 2>&1",
            "FIXTURE_RMMOD_RC=$?",
            f"echo REHARNESS_RUNTIME_FIXTURE_MODULE_{index}_RMMOD_RC"
            "=$FIXTURE_RMMOD_RC",
        ]
    lines += [
        "sleep 0.2",
        "# Quiesce the serial console before emitting the machine-readable "
        "completion marker.",
        "echo 0 > /proc/sys/kernel/printk 2>/dev/null",
        "printf '=== QEMU_RUN_DONE ===\\n'",
        "echo o > /proc/sysrq-trigger 2>/dev/null",
    ]
    init = rootfs / "init"
    init.write_text("\n".join(lines) + "\n")
    init.chmod(0o755)


def _build_initramfs(rootfs: Path, initramfs: Path) -> None:
    entries = "\0".join(
        p.relative_to(rootfs).as_posix()
        for p in rootfs.rglob("*")) + "\0"
    cpio = subprocess.run(
        ["cpio", "--null", "-o", "--format=newc"],
        cwd=rootfs, input=entries.encode(), capture_output=True)
    compressed = subprocess.run(
        ["gzip", "-9"], input=cpio.stdout, capture_output=True)
    initramfs.write_bytes(compressed.stdout)


# ── argument assembly (pure Python) ─────────────────────────────────────


def assemble_qemu_args(spec: GuestSpec, initramfs: Path) -> list[str]:
    args = [
        "-kernel", str(KERNEL_BZIMAGE),
        "-initrd", str(initramfs),
        "-M", spec.machine,
        "-append",
        "console=ttyS0 nokaslr panic=1 ignore_loglevel "
        "earlyprintk=serial,ttyS0,115200",
        "-nographic", "-m", "256M", "-smp", "2", "-no-reboot",
        "-monitor", "none",
    ]
    args += list(spec.qemu_args)
    if spec.launch_device and spec.device:
        args += ["-device", spec.device]
    return args


# ── judging ─────────────────────────────────────────────────────────────


_OOPS_RE = re.compile(
    r"Oops:|BUG:|Unable to handle|general protection|"
    r"Kernel panic - not syncing")
_WARNING_RE = re.compile(
    r"WARNING:\s+(CPU:\s+\d+\s+PID:\s+\d+\s+at\s+"
    r"|[A-Za-z0-9_.-]+/[^\s:]+:\d+\s+at\s+)")


def judge(serial: str, spec: GuestSpec) -> tuple[int, str]:
    """Return (exit_code, reason) using the preserved marker protocol."""
    lines = serial.splitlines()

    def count(pattern: str) -> int:
        regex = re.compile(pattern)
        return sum(1 for line in lines if regex.search(line))

    real_oops = sum(
        1 for line in lines
        if _OOPS_RE.search(line) and "Attempted to kill init" not in line)
    real_warning = sum(
        1 for line in lines
        if _WARNING_RE.search(line) and "Attempted to kill init" not in line)
    if real_oops:
        return 2, "kernel oops/crash"
    if real_warning:
        return 2, "kernel warning"

    done = count("QEMU_RUN_DONE")
    probe = count(spec.probe_pattern)
    bound = count(r"REHARNESS_DRIVER_PROBE_BOUND=1")
    ex_ok = True
    if spec.exerciser and not any(
            "EXERCISER_RC=0" in line for line in lines):
        ex_ok = False
    if spec.success_pattern:
        regex = re.compile(spec.success_pattern)
        if not any(regex.search(line) for line in lines):
            ex_ok = False
    inconclusive = False
    for index, item in enumerate(spec.subtests):
        prefix = f"REHARNESS_SUBSYSTEM_TEST_{index}_"
        rc_ok = any(line.startswith(f"{prefix}RC=0") for line in lines)
        success = rc_ok
        if item.success_pattern:
            regex = re.compile(item.success_pattern)
            if not any(regex.search(line) for line in lines):
                success = False
        if item.required and not success:
            ex_ok = False
        if (item.required and any(
                line.startswith(f"{prefix}STATUS=skip") for line in lines)):
            inconclusive = True
    for coverage_id in spec.coverage_required:
        if not any(
                f"REHARNESS_COVERAGE_{coverage_id}=pass" in line
                for line in lines):
            ex_ok = False
    unload_ok = any(
        line.startswith("REHARNESS_DRIVER_RMMOD_RC=0") for line in lines)
    if re.search(r"REHARNESS_RUNTIME_FIXTURE_MODULE_\d+_RMMOD_RC=[^0]", serial):
        unload_ok = False
    if not unload_ok:
        ex_ok = False

    if inconclusive:
        return 4, "subsystem test skipped"
    binding_ok = True
    if spec.binding_required and bound == 0:
        binding_ok = False
    if done and probe and binding_ok and ex_ok:
        return 0, f"{spec.module} probe 成功"
    if not ex_ok:
        return 3, "exerciser/subsystem semantic test failed"
    return 1, "未完成 probe"


# ── orchestration ───────────────────────────────────────────────────────


def run_guest(spec: GuestSpec, module_ko: Path, *, out_path: Path,
              run_dir: Path | None = None,
              extra_tests: Path | None = None,
              keep_runtime: bool = False,
              qemu_binary: str | None = None) -> dict[str, Any]:
    """One isolated guest run; returns serial/rc/judgement."""
    tmp_base = Path(os.environ.get("RH_QEMU_TMPDIR",
                                   os.environ.get("TMPDIR", "/tmp")))
    tmp_base.mkdir(parents=True, exist_ok=True)
    if run_dir is None:
        run_dir = Path(tempfile.mkdtemp(
            prefix=f"reharness-qemu-{spec.module}.", dir=tmp_base))
    rootfs = run_dir / "rootfs"
    initramfs = run_dir / "initramfs.cpio.gz"

    if spec.fixture is not None:
        plugin = FIXTURE_PLUGINS.get(spec.fixture.kind)
        if plugin is not None:
            plugin().prepare(FixtureContext(
                dict(spec.fixture.config or {}), run_dir))

    _build_rootfs(rootfs, spec, module_ko, extra_tests)
    _stage_kernel_modules(rootfs, spec)
    _fixture_assets(rootfs, spec)
    fixture_modules = _fixture_module_build(rootfs, spec)
    _build_init(rootfs, spec, fixture_modules)
    _build_initramfs(rootfs, initramfs)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    qemu_args = assemble_qemu_args(spec, initramfs)
    binary = qemu_binary or os.environ.get("RH_QEMU_BINARY",
                                           "qemu-system-x86_64")
    try:
        proc = subprocess.run(
            ["timeout", "--kill-after=5", str(spec.timeout), binary,
             *qemu_args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=spec.timeout + 15)
        rc = proc.returncode
        out_path.write_bytes(proc.stdout)
    except subprocess.TimeoutExpired:
        rc = 124
        out_path.write_text("TIMEOUT\n")

    serial = out_path.read_text(errors="replace")
    code, reason = judge(serial, spec)
    if not keep_runtime:
        shutil.rmtree(run_dir, ignore_errors=True)
    return {"rc": rc, "judge_code": code, "reason": reason,
            "serial_path": str(out_path), "serial": serial,
            "run_dir": str(run_dir) if keep_runtime else None}


def _module_output_root() -> Path:
    return Path(os.environ.get(
        "RH_QEMU_MODULE_OUTPUT_ROOT", ROOT / "artifacts/output"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = _load_manifest(
        args.manifest if args.manifest.is_absolute()
        else ROOT / args.manifest)
    spec = GuestSpec(manifest)

    output_root = _module_output_root()
    module_ko = output_root / spec.module / f"{spec.module}.ko"
    if not module_ko.is_file():
        print(f"先编译 {spec.module}")
        return 1

    out_path = Path(os.environ.get("RH_QEMU_OUT",
                                   tempfile.mkdtemp(prefix="reharness-qemu-")
                                   + "/qemu.log"))
    result = run_guest(spec, module_ko, out_path=out_path,
                       keep_runtime=os.environ.get("RH_QEMU_KEEP_RUNTIME")
                       == "1")
    print(f"=== QEMU 退出码: {result['rc']} ===")
    print(f"=== 成功判定: code={result['judge_code']} "
          f"({result['reason']}) ===")
    return result["judge_code"]



if __name__ == "__main__":
    raise SystemExit(main())
