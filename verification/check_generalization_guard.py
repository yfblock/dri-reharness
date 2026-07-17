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


def _git_object(path: Path, revision: str, relative: str) -> str:
    run = subprocess.run(
        ["git", "-C", str(path), "rev-parse", f"{revision}:{relative}"],
        capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else "unknown"


def _protected_root_changed(commit: str, relative: str) -> bool:
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", commit, "--", relative])
    untracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--others",
         "--exclude-standard", "--", relative],
        capture_output=True, text=True)
    return tracked.returncode != 0 or bool(untracked.stdout.strip())


def _selection_issues(data: dict, manifest_dir: Path) -> list[str]:
    selection = data.get("selection")
    if not selection:
        return []
    issues: list[str] = []
    seed = selection.get("seed")
    limits = selection.get("nonblank_loc", {})
    minimum = limits.get("minimum")
    maximum = limits.get("maximum")
    if not isinstance(seed, str) or not isinstance(minimum, int) \
            or not isinstance(maximum, int):
        return ["selection seed/nonblank LOC limits are invalid"]

    excluded: set[str] = set()
    v1_path = manifest_dir / "zero-shot-v1.json"
    if v1_path.is_file():
        v1 = json.loads(v1_path.read_text(encoding="utf-8"))
        excluded.update(Path(case["source"]).name for case in v1["cases"])
    excluded.update(path.name for path in (ROOT / "drivers" / "test").glob("*.c"))
    for path in (ROOT / "drivers" / "multisource").glob("*.json"):
        corpus = json.loads(path.read_text(encoding="utf-8"))
        excluded.update(Path(source).name for source in corpus.get("sources", []))

    cases = data.get("cases", [])
    selected_by_source = {}
    for index, case in enumerate(cases, 1):
        source = (manifest_dir / case.get("source", "")).resolve()
        try:
            relative = source.relative_to(ROOT / "linux").as_posix()
        except ValueError:
            issues.append(f"selection source outside Linux tree: {source}")
            continue
        expected_hash = hashlib.sha256(
            f"{seed}:{relative}".encode("utf-8")).hexdigest()
        if case.get("selection_hash") != expected_hash:
            issues.append(f"selection hash mismatch for {case.get('id')}")
        if case.get("selection_order") != index:
            issues.append(f"selection order mismatch for {case.get('id')}")
        selected_by_source[relative] = case.get("id")

    expected_all: list[str] = []
    for pool_name, pool in selection.get("pools", {}).items():
        try:
            signal = re.compile(pool["signal_regex"])
            quota = int(pool["quota"])
            glob = pool["glob"]
        except (KeyError, TypeError, ValueError, re.error):
            issues.append(f"invalid selection pool {pool_name}")
            continue
        candidates = []
        for source in (ROOT / "linux").glob(glob):
            if source.name in excluded:
                continue
            text = source.read_text(encoding="utf-8", errors="replace")
            nonblank = sum(bool(line.strip()) for line in text.splitlines())
            if not minimum <= nonblank <= maximum or not signal.search(text):
                continue
            relative = source.relative_to(ROOT / "linux").as_posix()
            rank = hashlib.sha256(
                f"{seed}:{relative}".encode("utf-8")).hexdigest()
            candidates.append((rank, relative))
        candidates.sort()
        chosen = [relative for _, relative in candidates[:quota]]
        if len(chosen) != quota:
            issues.append(
                f"selection pool {pool_name} has only {len(chosen)}/{quota} cases")
        expected_all.extend(chosen)

    actual = []
    for case in cases:
        source = (manifest_dir / case.get("source", "")).resolve()
        try:
            actual.append(source.relative_to(ROOT / "linux").as_posix())
        except ValueError:
            pass
    if actual != expected_all:
        issues.append("frozen case list differs from deterministic pool selection")
    return issues


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

    frozen = data.get("frozen_against", {})
    frozen_reharness = frozen.get("reharness_commit")
    for relative_root in data.get("policy", {}).get("protected_roots", []):
        expected_tree = frozen.get(f"{relative_root}_tree")
        if not expected_tree:
            continue
        actual_tree = _git_object(ROOT, frozen_reharness, relative_root)
        if actual_tree != expected_tree:
            issues.append(
                f"frozen {relative_root} tree mismatch: "
                f"frozen={expected_tree} actual={actual_tree}")
        if _protected_root_changed(frozen_reharness, relative_root):
            issues.append(
                f"protected root changed since frozen commit: {relative_root}")

    manifest_dir = manifest_path.parent
    issues.extend(_selection_issues(data, manifest_dir))
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
