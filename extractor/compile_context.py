"""Import preprocessing context from Linux compile_commands or Kbuild .cmd."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from dataclasses import dataclass
from functools import lru_cache


_PAIRED_PATH_FLAGS = {"-I", "-isystem", "-include", "-imacros", "-iquote", "-idirafter"}
_COMBINED_PATH_FLAGS = ("-isystem", "-include", "-imacros", "-iquote", "-idirafter", "-I")
_STANDALONE_FLAGS = {
    "-nostdinc", "-nostdinc++", "-fshort-wchar", "-funsigned-char",
    "-fms-extensions", "-fno-common", "-fno-strict-aliasing", "-m32", "-m64",
}
_CMD_RE = re.compile(r"^(?:saved)?cmd_[^ ]+\s*:=\s*(.+)$", re.M)


@dataclass(frozen=True)
class CompileContext:
    source: str
    arguments: tuple[str, ...]
    directory: str
    origin: str
    provenance: str
    raw_command_sha256: str

    def display(self) -> dict:
        encoded = "\0".join(self.arguments).encode("utf-8")
        return {
            "source": self.source,
            "origin": self.origin,
            "provenance": self.provenance,
            "directory": self.directory,
            "arguments": list(self.arguments),
            "argument_count": len(self.arguments),
            "arguments_sha256": hashlib.sha256(encoded).hexdigest(),
            "raw_command_sha256": self.raw_command_sha256,
        }


def _repo_roots(linux_root: str | None, build_root: str | None) -> tuple[str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.normpath(os.path.join(here, ".."))
    linux = os.path.abspath(linux_root or os.path.join(repo, "linux"))
    build = build_root or os.environ.get("REHARNESS_KERNEL_BUILD")
    if not build:
        build = os.path.join(repo, "kernel", "build")
    return linux, os.path.abspath(build)


def _resolve_path(value: str, directory: str) -> str:
    if not value or value.startswith(("$", "<")) or os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(directory, value))


def _sanitize_arguments(tokens: list[str], directory: str, source: str) -> tuple[str, ...]:
    """Keep the language/preprocessor portion of a kernel compile command.

    GCC code-generation and dependency flags are intentionally removed: they
    are irrelevant to libclang parsing and many are rejected by another clang
    version. Relative include paths are made absolute against the Kbuild cwd.
    """
    out: list[str] = []
    i = 0
    source_real = os.path.realpath(source)
    while i < len(tokens):
        token = tokens[i]
        if token in _PAIRED_PATH_FLAGS and i + 1 < len(tokens):
            out.extend([token, _resolve_path(tokens[i + 1], directory)])
            i += 2
            continue
        if token == "-x" and i + 1 < len(tokens):
            out.extend([token, tokens[i + 1]])
            i += 2
            continue
        combined = next((prefix for prefix in _COMBINED_PATH_FLAGS
                         if token.startswith(prefix) and token != prefix), None)
        if combined:
            value = token[len(combined):]
            out.append(combined + _resolve_path(value, directory))
            i += 1
            continue
        if token.startswith(("-D", "-U", "-std=", "-fstrict-flex-arrays=")):
            out.append(token)
        elif token in _STANDALONE_FLAGS:
            out.append(token)
        elif token.endswith((".c", ".cc", ".S")):
            candidate = _resolve_path(token, directory)
            if os.path.realpath(candidate) != source_real:
                # A non-target source token is not useful for this TU parse.
                pass
        i += 1

    if "-x" not in out:
        out[0:0] = ["-x", "c"]
    source_dir = os.path.dirname(os.path.abspath(source))
    if not any(arg == source_dir or arg == "-I" + source_dir for arg in out):
        out.extend(["-I", source_dir])
    return tuple(out)


def _context_from_tokens(source: str, tokens: list[str], directory: str,
                         origin: str, provenance: str, raw: str) -> CompileContext:
    return CompileContext(
        source=os.path.abspath(source),
        arguments=_sanitize_arguments(tokens, directory, source),
        directory=os.path.abspath(directory),
        origin=origin,
        provenance=os.path.abspath(provenance),
        raw_command_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


@lru_cache(maxsize=4)
def _load_compile_commands(path: str, mtime: float, size: int):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return []


def _from_compile_commands(source: str, path: str) -> CompileContext | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    entries = _load_compile_commands(path, stat.st_mtime, stat.st_size)
    target = os.path.realpath(source)
    for entry in entries if isinstance(entries, list) else []:
        directory = os.path.abspath(entry.get("directory") or os.path.dirname(path))
        file_path = _resolve_path(str(entry.get("file", "")), directory)
        if os.path.realpath(file_path) != target:
            continue
        if isinstance(entry.get("arguments"), list):
            tokens = [str(value) for value in entry["arguments"]]
            raw = "\0".join(tokens)
        else:
            raw = str(entry.get("command", ""))
            tokens = shlex.split(raw)
        return _context_from_tokens(
            source, tokens, directory, "compile-commands", path, raw)
    return None


def _cmd_path(source: str, linux_root: str, build_root: str) -> str | None:
    try:
        relative = os.path.relpath(os.path.abspath(source), linux_root)
    except ValueError:
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    stem, ext = os.path.splitext(relative)
    if ext != ".c":
        return None
    directory, name = os.path.split(stem)
    return os.path.join(build_root, directory, f".{name}.o.cmd")


def _from_kbuild_cmd(source: str, path: str, build_root: str) -> CompileContext | None:
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    match = _CMD_RE.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    compile_command = raw.split(";", 1)[0].strip()
    try:
        tokens = shlex.split(compile_command)
    except ValueError:
        return None
    return _context_from_tokens(
        source, tokens, build_root, "kbuild-cmd", path, compile_command)


def resolve_compile_context(source: str, linux_root: str | None = None,
                            compile_commands: str | None = None,
                            build_root: str | None = None,
                            mode: str = "auto") -> CompileContext | None:
    if mode not in {"off", "auto", "required"}:
        raise ValueError(f"invalid compile context mode: {mode}")
    if mode == "off":
        return None
    linux, build = _repo_roots(linux_root, build_root)
    database = compile_commands or os.environ.get("REHARNESS_COMPILE_COMMANDS")
    if not database:
        candidate = os.path.join(build, "compile_commands.json")
        database = candidate if os.path.isfile(candidate) else None
    if database:
        context = _from_compile_commands(source, os.path.abspath(database))
        if context:
            return context
    command_file = _cmd_path(source, linux, build)
    if command_file and os.path.isfile(command_file):
        return _from_kbuild_cmd(source, command_file, build)
    if mode == "required":
        raise RuntimeError(f"no Kbuild compile context found for {source}")
    return None


def compile_context_identity(source: str, linux_root: str | None = None,
                             compile_commands: str | None = None,
                             mode: str = "auto") -> tuple:
    if mode == "off":
        return ("off",)
    linux, build = _repo_roots(linux_root, None)
    database = compile_commands or os.environ.get("REHARNESS_COMPILE_COMMANDS")
    if not database:
        candidate = os.path.join(build, "compile_commands.json")
        database = candidate if os.path.isfile(candidate) else None
    paths = [database, _cmd_path(source, linux, build)]
    identity = []
    for path in paths:
        if not path:
            continue
        try:
            identity.append((os.path.abspath(path), os.path.getmtime(path), os.path.getsize(path)))
        except OSError:
            identity.append((os.path.abspath(path), 0, 0))
    return (mode, *identity)
