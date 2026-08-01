"""Manifest-backed adapters for the public experiment runner.

The adapters are deliberately thin.  They translate validated manifest data
into existing repository commands and return structured results; policy and
retry ordering remain in :mod:`experiment_runner`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from experiment_manifest import ExperimentManifest
from experiment_protocol import FailureClass, Feedback
from synthesis import SubprocessPiBridge
from trace_protocol import compare_runs, load_trace


ROOT = Path(__file__).resolve().parents[2]


def _failure(kind: FailureClass, message: str, details: Mapping[str, Any], stage: str) -> dict[str, Any]:
    return {"ok": False, "feedback": Feedback.from_failure(kind, message, details, stage=stage).to_dict()}


class ManifestExtractor:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root

    def extract(self, manifest: ExperimentManifest) -> dict[str, Any]:
        out = self.root / "artifacts" / "experiments" / manifest.name / "evidence"
        out.mkdir(parents=True, exist_ok=True)
        command = ["python3", "-m", "extractor", "bundle", "-s",
                   str(manifest.source.path), "-b", manifest.compile.backend, "-o", str(out)]
        completed = subprocess.run(command, cwd=self.root, text=True,
                                   capture_output=True, check=False)
        if completed.returncode:
            return _failure(FailureClass.EXTRACTION, "evidence extraction failed",
                            {"return_code": completed.returncode, "stderr": completed.stderr[-4000:]}, "extract")
        files = sorted(str(path.relative_to(self.root)) for path in out.iterdir() if path.is_file())
        digest = hashlib.sha256("\n".join(files).encode()).hexdigest()
        return {"ok": True, "value": {"directory": str(out), "files": files, "digest": digest},
                "payload": {"directory": str(out), "files": files, "digest": digest}}


class ManifestCompiler:
    """Compile an adapter-provided candidate using its declared context.

    A context may be a command template.  ``{source}``, ``{module}``, and
    ``{output}`` are substituted from manifest data; no target facts are
    inferred here.  The default context is intentionally fail-closed.
    """
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root

    def compile(self, manifest: ExperimentManifest, candidate: Any) -> dict[str, Any]:
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("code"), str):
            return _failure(FailureClass.CONTRACT, "candidate does not contain generated code", {}, "compile")
        out = self.root / "artifacts" / "experiments" / manifest.name / "candidate.c"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(candidate["code"], encoding="utf-8")
        context = manifest.compile.context
        if context.startswith("command:"):
            template = context.removeprefix("command:").strip()
            values = {"source": str(manifest.source.path), "module": manifest.runtime.module,
                      "output": str(out)}
            command = template.format(**values).split()
        else:
            return _failure(FailureClass.INFRASTRUCTURE,
                            "compile context has no configured command", {"context": context}, "compile")
        completed = subprocess.run(command, cwd=self.root, text=True,
                                   capture_output=True, check=False)
        if completed.returncode:
            return _failure(FailureClass.COMPILE, "candidate compilation failed",
                            {"return_code": completed.returncode, "stderr": completed.stderr[-8000:]}, "compile")
        return {"ok": True, "value": {"path": str(out), "module": manifest.runtime.module},
                "payload": {"path": str(out), "module": manifest.runtime.module}}


class ManifestRuntime:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root

    def run(self, manifest: ExperimentManifest, candidate: Any, scenario: Any, role: str) -> dict[str, Any]:
        module = manifest.runtime.module
        if isinstance(candidate, Mapping):
            module = str(candidate.get("module", module))
        command = ["bash", "scripts/qemu/qemu_run.sh", module,
                   "--bus", manifest.runtime.bus, "--timeout", str(manifest.runtime.timeout_seconds)]
        if manifest.runtime.device:
            command += ["--device", manifest.runtime.device]
        if manifest.runtime.registrar:
            command += ["--registrar-target", manifest.runtime.registrar]
        if manifest.test.executable:
            command += ["--exerciser", str(manifest.test.executable.relative_to(self.root)),
                        "--exerciser-args", " ".join(manifest.test.args)]
        if manifest.runtime.probe_pattern:
            command += ["--probe-pattern", manifest.runtime.probe_pattern]
        completed = subprocess.run(command, cwd=self.root, text=True,
                                   capture_output=True, check=False)
        trace_path = self.root / "artifacts" / "experiments" / manifest.name / f"{role}.trace"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            return _failure(FailureClass.RUNTIME, "runtime adapter failed",
                            {"role": role, "return_code": completed.returncode,
                             "trace": str(trace_path)}, role)
        return {"ok": True, "value": str(trace_path),
                "payload": {"role": role, "trace": str(trace_path)}}


class ManifestComparator:
    def compare(self, manifest: ExperimentManifest, baseline: Any, candidate: Any) -> dict[str, Any]:
        try:
            left = load_trace(baseline, config=manifest.trace.to_dict())
            right = load_trace(candidate, config=manifest.trace.to_dict())
            result = compare_runs(left, right)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _failure(FailureClass.INFRASTRUCTURE, "trace comparison failed", {"error": str(exc)}, "compare")
        return {"ok": result.equal, "value": result.to_dict(), "payload": result.to_dict(),
                **({} if result.equal else {"feedback": Feedback.from_failure(
                    FailureClass.TRACE, "register trace mismatch", result.to_dict(), stage="compare").to_dict()})}


class Adapters:
    def __init__(self, root: Path = ROOT) -> None:
        self.extractor = ManifestExtractor(root)
        self.pi = SubprocessPiBridge(str(root / "tools" / "pi" / "pi_synth.sh"))
        self.compiler = ManifestCompiler(root)
        self.runtime = ManifestRuntime(root)
        self.comparator = ManifestComparator()


def build_adapters(manifest: ExperimentManifest | None = None) -> Adapters:
    return Adapters()
