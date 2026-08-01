from __future__ import annotations

import ast
import configparser
import os
from pathlib import Path
import re
import stat


ROOT = Path(__file__).resolve().parents[2]

CANONICAL_DIRS = (
    "artifacts/output",
    "benchmarks/drivers/baseline",
    "benchmarks/drivers/holdout",
    "benchmarks/drivers/multisource",
    "docs",
    "examples/edu",
    "platform/kernel",
    "platform/rootfs/base",
    "platform/rootfs/platform",
    "platform/rootfs/runtime",
    "qa/native-tests",
    "qa/tests",
    "qa/verification",
    "research/experiments",
    "research/history",
    "research/paper",
    "research/reference-success",
    "scripts/e2e",
    "scripts/maintenance",
    "scripts/qemu",
    "src/extractor",
    "src/generator",
    "tools/pi",
    "vendor/linux",
)

LEGACY_ROOT_ENTRIES = (
    "drivers", "edu_drv.c", "experiments", "extractor", "generator",
    "history", "kernel", "linux", "log_event.sh", "output", "paper",
    "qemu_edu.sh", "qemu_platform.sh", "qemu_run.sh", "recom.md",
    "repo_paths.py", "run_e2e.sh", "run_edu_e2e.sh", "run_gpio_e2e.sh",
    "success", "synthesis.py", "test", "test_rootfs",
    "test_rootfs_plat", "test_rootfs_run", "tests", "verification",
    "plan.md", "initramfs_edu.cpio.gz", "initramfs_plat.cpio.gz",
    "initramfs_run.cpio.gz", "__pycache__",
)
ROOT_VARIABLE_NAMES = ("ROOT", "HERE", "PROJECT_DIR", "REPO_ROOT")
PYTHON_ROOT_VARIABLE_NAMES = {
    "here", "project_dir", "project_root", "reharness", "reharness_root",
    "repo_root", "repository_root", "root",
}

ALLOWED_ROOT_ENTRIES = {
    ".agents", ".codegraph", ".codex", ".git", ".gitignore",
    ".gitmodules", "PROMPT.md", "README.md", "REPRO.md", "artifacts",
    "benchmarks", "docs", "examples", "platform", "qa", "research",
    "run.sh", "scripts", "src", "tools", "vendor",
}

ACTIVE_SUFFIXES = {
    ".c", ".config", ".h", ".json", ".md", ".py", ".sh", ".tex",
    ".toml", ".yaml", ".yml",
}
ACTIVE_FILENAMES = {".gitignore", ".gitmodules", "Makefile"}
REFERENCE_EXCLUDED_DIRS = (
    ".git", "artifacts", "docs/superpowers", "platform/kernel/build",
    "research/history", "research/experiments/results",
    "tools/pi/node_modules", "vendor/linux",
)
_ROOT_VARIABLE_PATTERN = "|".join(ROOT_VARIABLE_NAMES)
_LEGACY_ROOT_ENTRY_PATTERN = "|".join(
    sorted((re.escape(entry) for entry in LEGACY_ROOT_ENTRIES),
           key=len, reverse=True)
)
ROOTED_LEGACY_REFERENCE = re.compile(
    rf"(?P<root_join>(?:"
    rf"\$(?:{_ROOT_VARIABLE_PATTERN}|\{{(?:{_ROOT_VARIABLE_PATTERN})\}})/|"
    rf"(?<![A-Za-z0-9_])(?:{_ROOT_VARIABLE_PATTERN})\s*/\s*[\"'])"
    rf"(?:{_LEGACY_ROOT_ENTRY_PATTERN})(?![A-Za-z0-9_.-]))"
)
LEGACY_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./<-])(?:"
    r"drivers/(?:test|holdout|multisource)/|"
    r"(?:extractor|generator|verification|tests|test|output|kernel|"
    r"experiments|paper|success|history|test_rootfs(?:_plat|_run)?)/|"
    r"(?:cd|pushd)\s+(?:\./)?(?:extractor|generator|verification|tests|"
    r"test|output|kernel|experiments|paper|success|history|linux|"
    r"test_rootfs(?:_plat|_run)?)(?![A-Za-z0-9_./-])|"
    r"(?P<linux_path>(?:\./|\.\./)*linux/"
    r"(?![^\s\"'()]+\.o(?=[\s\"')]|$)))|"
    r"(?P<legacy_file>(?:\./)?(?:edu_drv\.c|"
    r"initramfs_(?:edu|plat|run)\.cpio\.gz|"
    r"log_event\.sh|plan\.md|qemu_(?:edu|platform|run)\.sh|recom\.md|"
    r"repo_paths\.py|run_(?:e2e|edu_e2e|gpio_e2e)\.sh|synthesis\.py)"
    r"(?![A-Za-z0-9_.-]))"
    r")"
)
LINUX_INTERNAL_INCLUDE = re.compile(r"#\s*include\s*[<\"]linux/")
C_FAMILY_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp"}


def _is_active_file(path: Path) -> bool:
    return path.name in ACTIVE_FILENAMES or path.suffix in ACTIVE_SUFFIXES


def _legacy_reference_match(
        line: str, relative: str | None = None) -> re.Match[str] | None:
    match = ROOTED_LEGACY_REFERENCE.search(line)
    if match is None:
        match = LEGACY_REFERENCE.search(line)
    if match is None:
        return None
    stripped = line.lstrip()
    suppress_source_comment = (
        relative is None or Path(relative).suffix.lower() in C_FAMILY_SUFFIXES
    )
    if match.lastgroup == "linux_path":
        if LINUX_INTERNAL_INCLUDE.search(line):
            return None
        if suppress_source_comment and stripped.startswith(("//", "*")):
            return None
    if (match.lastgroup == "legacy_file"
            and suppress_source_comment
            and stripped.startswith(("#", "//", "*"))):
        return None
    if match.lastgroup == "legacy_file" and relative is not None:
        alias = match.group("legacy_file").removeprefix("./")
        if Path(relative).name == alias:
            return None
    return match


def _legacy_python_join_references(text: str) -> tuple[tuple[int, str], ...]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()

    references = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "join"
            and isinstance(function.value, ast.Attribute)
            and function.value.attr == "path"
            and isinstance(function.value.value, ast.Name)
            and function.value.value.id == "os"
        ):
            continue
        root = node.args[0]
        if not (isinstance(root, ast.Name)
                and root.id.casefold() in PYTHON_ROOT_VARIABLE_NAMES):
            continue

        components = []
        repository_relative = True
        for argument in node.args[1:]:
            if not (isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)):
                break
            value = argument.value.replace("\\", "/")
            if value.startswith("/"):
                repository_relative = False
                break
            for component in value.split("/"):
                if not component or component == ".":
                    continue
                if component == "..":
                    if components and components[-1] != "..":
                        components.pop()
                    else:
                        components.append(component)
                else:
                    components.append(component)

        if not repository_relative:
            continue
        repository_components = list(components)
        while (repository_components
               and repository_components[0] == ".."):
            repository_components.pop(0)
        if not repository_components:
            continue
        root_entry = repository_components[0]
        if root_entry not in LEGACY_ROOT_ENTRIES:
            continue
        source = ast.get_source_segment(text, node) or "os.path.join(...)"
        references.append((node.lineno, re.sub(r"\s+", " ", source)))
    return tuple(sorted(references))


def _is_excluded_directory(relative: str) -> bool:
    return any(relative == excluded or relative.startswith(f"{excluded}/")
               for excluded in REFERENCE_EXCLUDED_DIRS)


def _active_repository_files():
    for directory, dirnames, filenames in os.walk(ROOT):
        relative_directory = Path(directory).relative_to(ROOT)
        dirnames[:] = [
            name for name in dirnames
            if not _is_excluded_directory(
                (relative_directory / name).as_posix())
        ]
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(ROOT).as_posix()
            if relative == "qa/tests/test_repository_layout.py":
                continue
            if path.is_file() and _is_active_file(path):
                yield path


def _submodule_paths(text: str) -> tuple[str, ...]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return tuple(
        parser.get(section, "path")
        for section in parser.sections()
        if section.startswith("submodule ")
    )


def test_legacy_reference_pattern_covers_path_bearing_root_aliases():
    references = (
        "history/20260709-192315.txt",
        "test_rootfs/etc/init.d/rcS",
        "test_rootfs_plat/bin/driver",
        "test_rootfs_run/bin/runner",
        'ROOTFS_DIR="$PROJECT_DIR/test_rootfs_run"',
        "initramfs_edu.cpio.gz",
        "initramfs_plat.cpio.gz",
        "initramfs_run.cpio.gz",
        'INITRAMFS="$PROJECT_DIR/initramfs_run.cpio.gz"',
        "../../linux/drivers/usb/core/driver.c",
        "linux/drivers/usb/core/driver.c",
        'source = REPO_ROOT / "linux/drivers/usb/core/driver.c"',
        "extractor/cli.py",
        'extractor_root = ROOT / "extractor"',
        "generator/linux.py",
        "verification/compare.py",
        "tests/fixtures/control_flow.c",
        "test/edu_trace_test.c",
        "output/demo/result.ris",
        "kernel/build/vmlinux",
        "experiments/results/qemu.json",
        "paper/paper.tex",
        "success/Makefile",
        "./run_e2e.sh",
        "run_edu_e2e.sh",
        "run_gpio_e2e.sh",
        "qemu_run.sh",
        "qemu_edu.sh",
        "qemu_platform.sh",
        "log_event.sh",
        "edu_drv.c",
        "recom.md",
        "repo_paths.py",
        "synthesis.py",
        "plan.md",
    )
    missing = [reference for reference in references
               if _legacy_reference_match(reference) is None]
    assert not missing, missing


def test_legacy_reference_pattern_covers_root_variable_joins():
    shell_roots = ("$ROOT", "${ROOT}", "$HERE", "$PROJECT_DIR", "$REPO_ROOT")
    pathlib_roots = ("ROOT", "HERE", "PROJECT_DIR", "REPO_ROOT")
    references = (
        *(f'{root}/{entry}'
          for root in shell_roots for entry in LEGACY_ROOT_ENTRIES),
        *(f'{root} / "{entry}"'
          for root in pathlib_roots for entry in LEGACY_ROOT_ENTRIES),
        'ROOT / "linux/drivers/usb/core/driver.c"',
        'REPO_ROOT / "verification/compare.py"',
    )
    missing = [reference for reference in references
               if _legacy_reference_match(reference) is None]
    assert not missing, missing


def test_python_join_scanner_covers_common_root_variables_and_legacy_entries():
    source = '''\
build = os.path.join(ROOT, "kernel", "build")
tests = os.path.join(REHARNESS, "drivers", "test")
oracle = os.path.join(repo_root, "verification")
plan = os.path.join(PROJECT_ROOT, "plan.md")
history = os.path.join(repository_root, "history", "latest.txt")
'''
    references = _legacy_python_join_references(source)
    assert references == (
        (1, 'os.path.join(ROOT, "kernel", "build")'),
        (2, 'os.path.join(REHARNESS, "drivers", "test")'),
        (3, 'os.path.join(repo_root, "verification")'),
        (4, 'os.path.join(PROJECT_ROOT, "plan.md")'),
        (5, 'os.path.join(repository_root, "history", "latest.txt")'),
    )


def test_python_join_scanner_covers_parent_relative_legacy_paths():
    source = '''\
linux = os.path.join(here, "..", "linux")
build = os.path.join(here, "..", "kernel", "build")
oracle = os.path.join(project_root, ".", "..", "verification")
tests = os.path.join(repository_root, "work", "..", "..", "tests")
'''
    references = _legacy_python_join_references(source)
    assert references == (
        (1, 'os.path.join(here, "..", "linux")'),
        (2, 'os.path.join(here, "..", "kernel", "build")'),
        (3, 'os.path.join(project_root, ".", "..", "verification")'),
        (4, 'os.path.join(repository_root, "work", "..", "..", "tests")'),
    )


def test_python_join_scanner_ignores_canonical_and_unrelated_joins():
    source = '''\
build = os.path.join(ROOT, "platform", "kernel", "build")
tests = os.path.join(REHARNESS, "benchmarks", "drivers", "test")
oracle = os.path.join(repo_root, "qa", "verification")
cache = os.path.join(cache_root, "kernel", "build")
other = path.join(ROOT, "kernel", "build")
'''
    assert not _legacy_python_join_references(source)


def test_python_join_scanner_ignores_parent_relative_canonical_paths():
    source = '''\
extractor = os.path.join(here, "..", "src", "extractor")
tests = os.path.join(project_root, ".", "..", "qa", "tests")
linux = os.path.join(repository_root, "..", "vendor", "linux")
build = os.path.join(reharness_root, "tmp", "..", "..", "platform", "kernel", "build")
external = os.path.join(here, "/kernel", "build")
'''
    assert not _legacy_python_join_references(source)


def test_legacy_reference_pattern_ignores_canonical_and_linux_internal_paths():
    references = (
        "src/extractor/cli.py",
        "src/generator/linux.py",
        "qa/verification/compare.py",
        "qa/tests/test_repository_layout.py",
        "qa/native-tests/edu_trace_test.c",
        "artifacts/output/demo/result.ris",
        "platform/kernel/build/vmlinux",
        "research/experiments/results/qemu.json",
        "research/history/20260709-192315.txt",
        "research/paper/paper.tex",
        "research/reference-success/Makefile",
        "scripts/e2e/run_e2e.sh",
        "scripts/qemu/qemu_run.sh",
        "vendor/linux/drivers/usb/core/driver.c",
        "#include <linux/module.h>",
        '        "#include <linux/module.h>",',
        "obj-y += linux/built-in.o",
        "include/linux/compiler.h",
        " * linux/drivers/video/wmt_ge_rops.c",
        " * edu_drv.c - Synthesized driver",
        "# qemu_run.sh - canonical runner",
        '$ROOT/src/extractor/cli.py',
        '${ROOT}/src/generator/linux.py',
        '$HERE/qa/verification/compare.py',
        '$PROJECT_DIR/platform/kernel/build',
        '$REPO_ROOT/vendor/linux/drivers/usb/core/driver.c',
        'ROOT / "src/extractor"',
        'REPO_ROOT / "qa/verification"',
        'HERE / "include/linux/compiler.h"',
        'PROJECT_DIR / "platform/kernel/build"',
        '$ROOTED/extractor',
        '${ROOTED}/extractor',
        'MY_ROOT / "extractor"',
        'ROOTED / "extractor"',
        '$ROOT/extractor-old',
        'ROOT / "verification2"',
        '$ROOT/initramfs_run.cpio.gz.bak',
    )
    flagged = [reference for reference in references
               if _legacy_reference_match(reference) is not None]
    assert not flagged, flagged


def test_markdown_and_shell_comments_are_audited_for_legacy_guidance():
    assert _legacy_reference_match(
        "# Run qemu_run.sh for the old workflow",
        "README.md",
    ) is not None
    assert _legacy_reference_match(
        "# Run qemu_run.sh for the old workflow",
        "scripts/example.sh",
    ) is not None


def test_c_source_comments_still_ignore_legacy_file_mentions():
    assert _legacy_reference_match(
        "// qemu_run.sh compatibility notes",
        "src/example.c",
    ) is None
    assert _legacy_reference_match(
        " * qemu_run.sh compatibility notes",
        "src/example.h",
    ) is None


def test_legacy_file_aliases_ignore_canonical_self_mentions_only():
    assert _legacy_reference_match(
        'MODULE_NAME="${1:?usage: qemu_run.sh <module>}"',
        "scripts/qemu/qemu_run.sh",
    ) is None
    assert _legacy_reference_match(
        "bash qemu_run.sh driver.ko",
        "scripts/e2e/run_e2e.sh",
    ) is not None


def test_active_file_selection_includes_extensionless_contract_files():
    paths = (Path(".gitignore"), Path(".gitmodules"), Path("Makefile"))
    missing = [path.name for path in paths if not _is_active_file(path)]
    assert not missing, missing


def test_reference_exclusions_use_directory_boundaries():
    assert _is_excluded_directory("docs/superpowers/plans")
    assert _is_excluded_directory("platform/kernel/build/include")
    assert _is_excluded_directory("vendor/linux/drivers")
    assert not _is_excluded_directory("docs/superpowers-old")
    assert not _is_excluded_directory("vendor/linux-notes")


def test_canonical_repository_layout_exists():
    invalid = [path for path in CANONICAL_DIRS
               if not (ROOT / path).is_dir() or (ROOT / path).is_symlink()]
    assert not invalid, invalid


def test_legacy_root_entries_are_absent():
    present = [path for path in LEGACY_ROOT_ENTRIES
               if (ROOT / path).exists() or (ROOT / path).is_symlink()]
    assert not present, present


def test_root_run_sh_is_a_real_executable_file():
    entry = ROOT / "run.sh"
    assert entry.is_file()
    assert not entry.is_symlink()
    assert stat.S_IMODE(entry.stat().st_mode) & stat.S_IXUSR


def test_linux_submodule_uses_the_canonical_path():
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    assert _submodule_paths(text) == ("vendor/linux",)


def test_root_contains_only_the_public_contract():
    unexpected = sorted(path.name for path in ROOT.iterdir()
                        if path.name not in ALLOWED_ROOT_ENTRIES)
    assert not unexpected, unexpected


def test_relocated_root_plan_exists():
    assert (ROOT / "docs/plans/original-implementation-plan.md").is_file()


def test_active_files_use_canonical_repository_paths():
    violations = []
    for path in _active_repository_files():
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        reported_lines = set()
        for number, line in enumerate(
                text.splitlines(), 1):
            match = _legacy_reference_match(line, relative)
            if match:
                violations.append(f"{relative}:{number}: {match.group(0)}")
                reported_lines.add(number)
        if path.suffix == ".py":
            for number, reference in _legacy_python_join_references(text):
                if number not in reported_lines:
                    violations.append(f"{relative}:{number}: {reference}")
    assert not violations, "\n".join(violations)


def _run_standalone() -> int:
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for name, test in tests:
        try:
            test()
        except Exception as error:
            failed += 1
            print(f"FAIL {name}: {type(error).__name__}: {error}")
        else:
            print(f"PASS {name}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
