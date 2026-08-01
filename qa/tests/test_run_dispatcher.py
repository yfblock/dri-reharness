from __future__ import annotations

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COMMANDS = (
    "extract", "spec", "gen", "driver", "facts", "bundle", "metrics",
    "score", "reliability", "compare", "test", "e2e", "experiment", "edu-e2e",
    "gpio-e2e", "qemu", "qemu-edu", "qemu-platform",
    "qemu-experiments", "log-event",
)
HELP_COMMAND_LINE = re.compile(
    r"^  ([a-z][a-z0-9-]*)(?:[ \t]|$)")


def _help_command_tokens(help_text: str) -> tuple[str, ...]:
    lines = iter(help_text.splitlines())
    for line in lines:
        if line.strip() == "Commands:":
            break
    else:
        return ()

    commands = []
    for line in lines:
        if not line.strip():
            if commands:
                break
            continue
        match = HELP_COMMAND_LINE.match(line)
        if match is None:
            break
        commands.append(match.group(1))
    return tuple(commands)


def test_help_command_tokens_come_only_from_the_commands_section():
    help_text = """Commands:
  extract <src>  extract a source file

Notes mention qemu-edu and log-event outside the command list.
  qemu-platform-extra  not an expected public command
    test  over-indented prose
"""
    assert _help_command_tokens(help_text) == ("extract",)


def test_help_command_tokens_stop_before_an_indented_explanatory_note():
    help_text = """Commands:
  extract <src>  extract a source file
  spec <src>     infer a specification

  note  this prose is outside the Commands section
"""
    assert _help_command_tokens(help_text) == ("extract", "spec")


def test_help_lists_every_public_command():
    result = subprocess.run(
        [str(ROOT / "run.sh"), "help"], cwd=ROOT,
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    commands = set(_help_command_tokens(result.stdout))
    missing = [command for command in EXPECTED_COMMANDS
               if command not in commands]
    assert not missing, missing


def test_unknown_command_fails():
    result = subprocess.run(
        [str(ROOT / "run.sh"), "not-a-command"], cwd=ROOT,
        capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "unknown command" in result.stdout + result.stderr


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
