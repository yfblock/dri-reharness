#!/usr/bin/env python3
"""Inject whole-driver function-coverage probes into a kernel module source.

Every file-scope function definition gets an entry probe
``pr_info("[rhcov] <name>\\n");``.  At judge time the executed set is read
from the guest serial log and compared against the inventory written to
``<output>.rhcov.json`` — yielding whole-driver function coverage.

Line-based scanner: a function definition is a signature line (contains ``(``,
no ``;``, no ``=`` before the paren, name not a control keyword) whose opening
brace appears on the same or one of the next few lines (no ``;`` in between).
Orthogonal to instrument_mmio's ``[rhfn]`` MMIO markers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SIG = re.compile(r'^[ \t]*(?:static[ \t]+)?[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)[ \t]*\(')
_KEYWORDS = {"if", "for", "while", "switch", "return", "else", "do",
             "sizeof", "defined"}
_MAX_LOOKAHEAD = 5


def inject(source_text: str) -> tuple[str, list[str]]:
    lines = source_text.splitlines(keepends=True)
    out: list[str] = []
    inventory: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _SIG.match(line)
        accepted = False
        if m:
            name = m.group(1)
            paren = line.find("(")
            before_paren = line[:paren]
            if (name not in _KEYWORDS and ";" not in line
                    and "=" not in before_paren):
                brace_line = None
                for j in range(i, min(i + _MAX_LOOKAHEAD, len(lines))):
                    if ";" in lines[j]:
                        break
                    if "{" in lines[j]:
                        brace_line = j
                        break
                if brace_line is not None:
                    inventory.append(name)
                    out.extend(lines[i:brace_line + 1])
                    indent = re.match(r"[ \t]*", lines[brace_line]).group(0) or "\t"
                    var = f"__rhcov_fn_{name}"
                    out.append(f'{indent}{{ static char {var} = 0; if (!{var}) {{ {var} = 1; pr_info("[rhcov] {name}\\n"); }} }}\n')
                    i = brace_line + 1
                    accepted = True
        if not accepted:
            out.append(line)
            i += 1
    return "".join(out), inventory


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path, nargs="+")
    ap.add_argument("--inventory-output", type=Path, required=True)
    ap.add_argument("--in-place", action="store_true")
    ns = ap.parse_args(argv)

    inventory: list[str] = []
    for src in ns.source:
        instrumented, functions = inject(src.read_text(encoding="utf-8"))
        inventory.extend(functions)
        if ns.in_place:
            src.write_text(instrumented, encoding="utf-8")
        else:
            sys.stdout.write(instrumented)
    ns.inventory_output.write_text(
        json.dumps({"functions": inventory}, indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    print(f"[rhcov] instrumented {len(inventory)} functions -> "
          f"{ns.inventory_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
