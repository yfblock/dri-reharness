#!/usr/bin/env python3
"""Validate the frozen zero-shot corpus and reject driver-specific tuning."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDOUT = ROOT / "drivers" / "holdout" / "zero-shot-v1.json"
TEXT_SUFFIXES = {".py", ".c", ".h", ".json", ".md", ".toml", ".yaml", ".yml"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_rev(path: Path) -> str:
    run = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else "unknown"


def _identifier_pattern(identifier: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])",
        re.IGNORECASE)


def _specialization_inventory() -> dict[str, list[str]]:
    basename_values: set[str] = set()
    device_values: set[str] = set()
    basename_re = re.compile(
        r"os\.path\.basename\(source\)\s*==\s*['\"]([^'\"]+)['\"]")
    device_re = re.compile(
        r"(?:device_spec\.name|\bdev)\s*==\s*['\"]([^'\"]+)['\"]")
    for relative in ("extractor", "generator"):
        for path in (ROOT / relative).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            basename_values.update(basename_re.findall(text))
            device_values.update(device_re.findall(text))

    layouts: set[str] = set()
    mmio_path = ROOT / "extractor" / "mmio.py"
    tree = ast.parse(mmio_path.read_text(encoding="utf-8"), filename=str(mmio_path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        if not names.intersection({"PRIVATE_MMIO_READ_LAYOUTS", "PRIVATE_MMIO_WRITE_LAYOUTS"}):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    layouts.add(key.value)
    return {
        "source_basename_equals": sorted(basename_values),
        "device_name_equals": sorted(device_values),
        "private_mmio_layouts": sorted(layouts),
    }


def check_guard(holdout_path: str | os.PathLike[str] = DEFAULT_HOLDOUT) -> dict:
    manifest_path = Path(holdout_path).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    issues: list[str] = []
    if data.get("schema") != 1 or not data.get("policy", {}).get("selection_locked"):
        issues.append("holdout schema/policy is not frozen")

    frozen_linux = data.get("frozen_against", {}).get("linux_commit")
    actual_linux = _git_rev(ROOT / "linux")
    if frozen_linux != actual_linux:
        issues.append(
            f"Linux submodule drift: frozen={frozen_linux} actual={actual_linux}")

    manifest_dir = manifest_path.parent
    cases = data.get("cases", [])
    if not cases or data.get("first_run") not in {case.get("id") for case in cases}:
        issues.append("holdout cases or first_run are invalid")

    patterns: list[tuple[str, re.Pattern[str]]] = []
    for case in cases:
        source = (manifest_dir / case.get("source", "")).resolve()
        if not source.is_file():
            issues.append(f"missing holdout source: {source}")
            continue
        actual_sha = _sha256(source)
        if actual_sha != case.get("source_sha256"):
            issues.append(
                f"source hash drift for {case.get('id')}: "
                f"frozen={case.get('source_sha256')} actual={actual_sha}")
        for identifier in case.get("forbidden_identifiers", []):
            patterns.append((identifier, _identifier_pattern(identifier)))

    protected = data.get("policy", {}).get("protected_roots", [])
    for relative_root in protected:
        root = (ROOT / relative_root).resolve()
        if not root.is_dir():
            issues.append(f"missing protected root: {relative_root}")
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for identifier, pattern in patterns:
                match = pattern.search(text)
                if match:
                    line = text.count("\n", 0, match.start()) + 1
                    issues.append(
                        f"holdout specialization {identifier!r} in "
                        f"{path.relative_to(ROOT)}:{line}")

    inventory = _specialization_inventory()
    allowed = data.get("policy", {}).get("specialization_allowlist", {})
    for category, values in inventory.items():
        extra = sorted(set(values) - set(allowed.get(category, [])))
        if extra:
            issues.append(
                f"new {category} specialization(s): {', '.join(extra)}")

    return {
        "schema": 1,
        "holdout": data.get("name"),
        "cases": len(cases),
        "first_run": data.get("first_run"),
        "linux_commit": actual_linux,
        "specialization_inventory": inventory,
        "issues": issues,
        "passed": not issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    args = parser.parse_args()
    report = check_guard(args.holdout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
