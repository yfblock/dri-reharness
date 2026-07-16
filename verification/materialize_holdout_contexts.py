#!/usr/bin/env python3
"""Materialize auditable Kbuild commands for every frozen holdout source."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractor.compile_context import (  # noqa: E402
    kbuild_cmd_path,
    read_kbuild_command,
    resolve_compile_context,
)
from verification.check_generalization_guard import (  # noqa: E402
    DEFAULT_HOLDOUT,
    check_guard,
)


DEFAULT_RECIPES = ROOT / "drivers" / "holdout" / "zero-shot-v1-contexts.json"


def validate_recipes(holdout: dict, recipes: dict) -> list[str]:
    """Return structural problems in the versioned context recipe."""
    issues: list[str] = []
    cases = {case.get("id"): case for case in holdout.get("cases", [])}
    recipe_cases = recipes.get("cases", {})
    profiles = recipes.get("profiles", {})
    if recipes.get("holdout") != holdout.get("name"):
        issues.append("context recipe names a different holdout")
    if set(cases) != set(recipe_cases):
        issues.append("context recipes do not cover the frozen holdout exactly")
    for case_id, recipe in recipe_cases.items():
        if recipe.get("profile") not in profiles:
            issues.append(
                f"{case_id} references missing profile {recipe.get('profile')!r}")
        case = cases.get(case_id)
        if not case:
            continue
        source = (ROOT / "drivers" / "holdout" / case["source"]).resolve()
        try:
            source_relative = source.relative_to(ROOT / "linux")
        except ValueError:
            issues.append(f"{case_id} source is outside the Linux tree")
            continue
        expected_target = source_relative.with_suffix(".o").as_posix()
        if recipe.get("target") != expected_target:
            issues.append(
                f"{case_id} target mismatch: expected {expected_target}, "
                f"got {recipe.get('target')!r}")
    for profile_name, profile in profiles.items():
        for field in ("arch", "build_dir", "cc", "kind"):
            if not profile.get(field):
                issues.append(f"profile {profile_name} lacks {field}")
    return issues


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


def _tool_version(tool: str) -> str:
    path = shutil.which(tool) or tool
    run = subprocess.run([path, "--version"], capture_output=True, text=True)
    return (run.stdout or run.stderr).splitlines()[0].strip()


def _find_lld() -> Path:
    configured = os.environ.get("REHARNESS_LD_LLD")
    candidates = [Path(configured)] if configured else []
    found = shutil.which("ld.lld")
    if found:
        candidates.append(Path(found))
    candidates.extend(sorted(
        Path.home().glob(
            ".rustup/toolchains/*/lib/rustlib/*/bin/gcc-ld/ld.lld")))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise RuntimeError(
        "PowerPC holdout context requires ld.lld; set REHARNESS_LD_LLD")


def _run_make(profile: dict, build: Path, target: str,
              env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = [
        "make", "-s", "-C", str(ROOT / "linux"), f"O={build}",
        f"ARCH={profile['arch']}", f"CC={profile['cc']}", "HOSTCC=gcc",
    ]
    if profile.get("requires_lld"):
        command.append("LD=ld.lld")
    command.append(target)
    return subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True,
        timeout=300)


def materialize(holdout_path: Path, recipes_path: Path,
                database_path: Path, report_path: Path) -> dict:
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
    guard = check_guard(holdout_path)
    if not guard["passed"]:
        raise RuntimeError("holdout guard failed: " + "; ".join(guard["issues"]))
    recipe_issues = validate_recipes(holdout, recipes)
    if recipe_issues:
        raise RuntimeError("invalid context recipes: " + "; ".join(recipe_issues))
    cases = {case["id"]: case for case in holdout["cases"]}

    profile_cases: dict[str, list[str]] = {}
    for case_id, recipe in recipes["cases"].items():
        profile_cases.setdefault(recipe["profile"], []).append(case_id)

    database_entries: list[dict] = []
    context_rows: list[dict] = []
    profile_rows: dict[str, dict] = {}
    for profile_name, case_ids in profile_cases.items():
        profile = recipes["profiles"][profile_name]
        build = (ROOT / profile["build_dir"]).resolve()
        build.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        lld = None
        if profile.get("requires_lld"):
            lld = _find_lld()
            env["PATH"] = str(lld.parent) + os.pathsep + env.get("PATH", "")

        defconfig = profile.get("defconfig")
        if defconfig:
            configured = _run_make(profile, build, defconfig, env)
            if configured.returncode != 0:
                raise RuntimeError(
                    f"{profile_name} defconfig failed: "
                    + (configured.stderr or configured.stdout)[-4000:])
        elif not (build / ".config").is_file():
            raise RuntimeError(f"pinned build lacks .config: {build}")

        profile_rows[profile_name] = {
            "arch": profile["arch"],
            "build_dir": os.path.relpath(build, ROOT),
            "cc": profile["cc"],
            "cc_version": _tool_version(profile["cc"]),
            "defconfig": defconfig,
            "kind": profile["kind"],
            "config_sha256": _sha256(build / ".config"),
            "lld": str(lld) if lld else None,
        }

        for case_id in sorted(case_ids):
            case = cases[case_id]
            case_recipe = recipes["cases"][case_id]
            built = _run_make(profile, build, case_recipe["target"], env)
            if built.returncode != 0:
                raise RuntimeError(
                    f"{case_id} Kbuild failed: "
                    + (built.stderr or built.stdout)[-4000:])
            source = (holdout_path.parent / case["source"]).resolve()
            cmd_name = kbuild_cmd_path(
                str(source), str(ROOT / "linux"), str(build))
            cmd_path = Path(cmd_name) if cmd_name else None
            command = read_kbuild_command(str(cmd_path)) if cmd_path else None
            if not cmd_path or not cmd_path.is_file() or not command:
                raise RuntimeError(f"{case_id} produced no auditable Kbuild .cmd")
            database_entries.append({
                "directory": str(build),
                "file": str(source),
                "command": command,
            })
            context_rows.append({
                "case": case_id,
                "source": os.path.relpath(source, ROOT),
                "profile": profile_name,
                "profile_kind": profile["kind"],
                "arch": profile["arch"],
                "defconfig": defconfig,
                "target": case_recipe["target"],
                "context_note": case_recipe.get("context_note"),
                "command_file": os.path.relpath(cmd_path, ROOT),
                "command_file_sha256": _sha256(cmd_path),
                "raw_command_sha256": hashlib.sha256(
                    command.encode("utf-8")).hexdigest(),
            })

    database_entries.sort(key=lambda entry: entry["file"])
    context_rows.sort(key=lambda row: row["case"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.write_text(
        json.dumps(database_entries, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    resolved_by_case = {}
    for row in context_rows:
        source = (ROOT / row["source"]).resolve()
        context = resolve_compile_context(
            str(source), linux_root=str(ROOT / "linux"),
            compile_commands=str(database_path), mode="required")
        if context is None or context.origin != "compile-commands":
            raise RuntimeError(
                f"{row['case']} did not resolve through the merged compile database")
        display = context.display()
        display["directory"] = os.path.relpath(display["directory"], ROOT)
        display["provenance"] = os.path.relpath(display["provenance"], ROOT)
        display["source"] = os.path.relpath(display["source"], ROOT)
        display.pop("arguments", None)
        resolved_by_case[row["case"]] = display
    for row in context_rows:
        row["resolved_context"] = resolved_by_case[row["case"]]
    report = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "holdout": holdout["name"],
        "environment": {
            "reharness_commit": _git_rev(ROOT),
            "linux_commit": _git_rev(ROOT / "linux"),
        },
        "guard": guard,
        "recipe_validation": {"issues": [], "passed": True},
        "compile_database": os.path.relpath(database_path, ROOT),
        "compile_database_sha256": _sha256(database_path),
        "exact_contexts": len(context_rows),
        "expected_contexts": len(cases),
        "profiles": profile_rows,
        "contexts": context_rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--recipes", default=str(DEFAULT_RECIPES))
    parser.add_argument(
        "--database", default=str(
            ROOT / "output" / "zero-shot-contexts" / "compile_commands.json"))
    parser.add_argument(
        "--output", default=str(
            ROOT / "experiments" / "results" / "zero-shot-contexts.json"))
    args = parser.parse_args()
    report = materialize(
        Path(args.holdout).resolve(), Path(args.recipes).resolve(),
        Path(args.database).resolve(), Path(args.output).resolve())
    print(json.dumps({
        "exact_contexts": report["exact_contexts"],
        "expected_contexts": report["expected_contexts"],
        "compile_database": report["compile_database"],
        "profiles": sorted(report["profiles"]),
    }, indent=2, sort_keys=True))
    return 0 if report["exact_contexts"] == report["expected_contexts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
