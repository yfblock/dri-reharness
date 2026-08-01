from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

if __package__:
    from ._bootstrap import QA_ROOT, REPO_ROOT, SOURCE_ROOT, resolve_logical
else:
    from _bootstrap import QA_ROOT, REPO_ROOT, SOURCE_ROOT, resolve_logical


_CANONICAL_REPO_PATHS = Path(resolve_logical.__code__.co_filename).resolve()


def _run_import_probe(
        script: str,
        *,
        pythonpath: tuple[Path, ...] = (SOURCE_ROOT, QA_ROOT),
        cwd: Path = Path("/tmp"),
) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        str(path.resolve()) for path in pythonpath)
    result = subprocess.run(
        [sys.executable, "-c", script, str(_CANONICAL_REPO_PATHS)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_canonical_first_import_has_single_identity_and_canonical_origin():
    output = _run_import_probe(r'''
from pathlib import Path
import sys

import verification.repo_paths as canonical
import repo_paths as bare

expected = Path(sys.argv[1]).resolve()
assert canonical is bare
assert Path(canonical.__file__).resolve() == expected
assert Path(canonical.__spec__.origin).resolve() == expected
assert Path(bare.__file__).resolve() == expected
assert Path(bare.__spec__.origin).resolve() == expected
print("canonical-first: PASS")
''')
    assert output == "canonical-first: PASS\n"


def test_bare_first_import_has_single_identity_and_canonical_origin():
    output = _run_import_probe(r'''
from pathlib import Path
import sys

import repo_paths as bare
import verification.repo_paths as canonical

expected = Path(sys.argv[1]).resolve()
assert bare is canonical
assert Path(bare.__file__).resolve() == expected
assert Path(bare.__spec__.origin).resolve() == expected
assert Path(canonical.__file__).resolve() == expected
assert Path(canonical.__spec__.origin).resolve() == expected
print("bare-first: PASS")
''', pythonpath=(QA_ROOT / "verification", SOURCE_ROOT, QA_ROOT))
    assert output == "bare-first: PASS\n"


def test_bootstrap_loads_canonical_origin_with_root_cwd_and_pythonpath():
    output = _run_import_probe(r'''
from pathlib import Path
import sys

from qa.tests import _bootstrap
import verification.repo_paths as canonical

expected = Path(sys.argv[1]).resolve()
assert canonical is _bootstrap._repo_paths
assert Path(canonical.__file__).resolve() == expected
assert Path(canonical.__spec__.origin).resolve() == expected
print("bootstrap-origin: PASS")
''', cwd=REPO_ROOT)
    assert output == "bootstrap-origin: PASS\n"


def test_repo_paths_refuses_a_different_preloaded_module():
    output = _run_import_probe(r'''
import sys
import types

sys.modules["repo_paths"] = types.ModuleType("repo_paths")
try:
    import verification.repo_paths
except RuntimeError as error:
    assert "different module" in str(error)
else:
    raise AssertionError("different repo_paths module was silently replaced")
print("module-conflict: PASS")
''')
    assert output == "module-conflict: PASS\n"


def test_repository_root_is_discovered_without_rewriting_dunder_file():
    tree = ast.parse(_CANONICAL_REPO_PATHS.read_text(encoding="utf-8"))
    assigned_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else (node.target,)
        )
        if isinstance(target, ast.Name)
    }

    assert "__file__" not in assigned_names
    assert (REPO_ROOT / ".gitmodules").is_file()
    assert (REPO_ROOT / "README.md").is_file()
    assert REPO_ROOT == Path(__file__).resolve().parents[2]


def test_repository_python_paths_are_canonical():
    assert SOURCE_ROOT == Path(__file__).resolve().parents[2] / "src"
    assert QA_ROOT == Path(__file__).resolve().parents[1]


def test_repository_python_paths_are_deduplicated_and_prepend_canonical_order():
    import sys
    from verification.repo_paths import install_python_paths

    original = list(sys.path)

    def equivalent(entry: object, target: Path) -> bool:
        try:
            return Path(entry or ".").resolve() == target.resolve()
        except (OSError, TypeError):
            return False

    sys.path[:] = [
        "/tmp/reharness-shadow",
        str(QA_ROOT),
        f"{SOURCE_ROOT}/",
        str(SOURCE_ROOT),
        f"{QA_ROOT}/",
        *original,
    ]
    try:
        install_python_paths()
        install_python_paths()

        assert sys.path[:2] == [str(SOURCE_ROOT), str(QA_ROOT)]
        assert sum(equivalent(item, SOURCE_ROOT) for item in sys.path) == 1
        assert sum(equivalent(item, QA_ROOT) for item in sys.path) == 1
    finally:
        sys.path[:] = original


def test_canonical_relative_paths_resolve_without_symlinks():
    base = REPO_ROOT / "benchmarks/drivers/holdout"
    resolved = resolve_logical(base, "../../../vendor/linux/README")
    assert resolved == (REPO_ROOT / "vendor/linux/README").resolve()


def test_canonical_holdout_base_resolves_into_repo():
    base = REPO_ROOT / "benchmarks" / "drivers" / "holdout"
    assert base.is_dir()
    assert not base.is_symlink()
    resolved = resolve_logical(base, "../../../vendor/linux/README")
    expected = (REPO_ROOT / "vendor/linux/README").resolve()
    assert resolved == expected
    assert resolved.is_relative_to(REPO_ROOT.resolve())
    assert resolved.is_file()


def test_canonical_multisource_base_resolves_into_repo():
    base = REPO_ROOT / "benchmarks" / "drivers" / "multisource"
    assert base.is_dir()
    assert not base.is_symlink()
    resolved = resolve_logical(
        base, "../../../vendor/linux/drivers/usb/dwc2/core.c")
    expected = (REPO_ROOT / "vendor/linux/drivers/usb/dwc2/core.c").resolve()
    assert resolved == expected
    assert resolved.is_relative_to(REPO_ROOT.resolve())
    assert resolved.is_file()


def test_all_holdout_sources_resolve_inside_repo_from_canonical_manifest():
    import json

    manifest = json.loads((
        REPO_ROOT / "benchmarks" / "drivers" / "holdout" /
        "zero-shot-v1.json"
    ).read_text(encoding="utf-8"))
    root = REPO_ROOT.resolve()
    assert manifest["cases"], "holdout manifest has no cases"
    for case in manifest["cases"]:
        source = resolve_logical(
            REPO_ROOT / "benchmarks" / "drivers" / "holdout",
            case["source"])
        assert source.is_relative_to(root), (
            f"{case['id']} source escapes repository: {source}")
        assert source.is_file(), f"{case['id']} source missing: {source}"


def test_all_multisource_sources_resolve_inside_repo_from_canonical_manifests():
    import json

    root = REPO_ROOT.resolve()
    manifest_dir = REPO_ROOT / "benchmarks" / "drivers" / "multisource"
    manifests = sorted(manifest_dir.glob("*.json"))
    assert manifests, "no multisource manifests found"
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative in manifest.get("sources", []):
            source = resolve_logical(manifest_path.parent, relative)
            assert source.is_relative_to(root), (
                f"{manifest_path} source escapes repository: {source}")
            assert source.is_file(), (
                f"{manifest_path} source missing: {source}")


def test_extractor_resolves_canonical_multisource_manifest():
    from extractor.extractor import _resolve_sources, ExtractorConfig

    manifest_rel = "benchmarks/drivers/multisource/c67x00.json"
    sources, name, descriptor = _resolve_sources(
        ExtractorConfig(source=manifest_rel))
    assert name == "c67x00"
    root = REPO_ROOT.resolve()
    assert len(sources) >= 4
    for source in sources:
        resolved = Path(source).resolve()
        assert resolved.is_relative_to(root), (
            f"{manifest_rel} source escapes repository: {source}")
        assert resolved.is_file(), f"{manifest_rel} source missing: {source}"


def test_holdout_manifest_uses_canonical_linux_relative_path():
    import json

    manifest = json.loads((
        REPO_ROOT / "benchmarks/drivers/holdout/zero-shot-v1.json"
    ).read_text(encoding="utf-8"))
    assert manifest["cases"][0]["source"].startswith(
        "../../../vendor/linux/")


def test_compile_context_defaults_accept_canonical_linux_source_path():
    from extractor.compile_context import resolve_compile_context

    source = REPO_ROOT / "vendor/linux/drivers/gpio/gpio-altera.c"
    context = resolve_compile_context(str(source), mode="required")

    assert context is not None
    assert context.origin == "kbuild-cmd"
    assert Path(context.provenance) == (
        REPO_ROOT /
        "platform/kernel/build/drivers/gpio/.gpio-altera.o.cmd")


def _run_standalone() -> int:
    import sys
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc(file=sys.stdout)
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
