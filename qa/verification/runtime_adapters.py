"""Manifest-backed adapters for the public experiment runner.

The adapters are deliberately thin.  They translate validated manifest data
into existing repository commands and return structured results; policy and
retry ordering remain in :mod:`experiment_runner`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from experiment_manifest import ExperimentManifest
from experiment_protocol import FailureClass, Feedback
from synthesis import SubprocessPiBridge
from trace_protocol import compare_runs, load_trace
from verification.backend_lowering_oracle import verify_backend_lowering
from tools.source.sanitize import SafetyPolicyError, sanitize_source


ROOT = Path(__file__).resolve().parents[2]


class RuntimeAdapterError(ValueError):
    """Raised when a manifest names an unavailable runtime adapter."""


class RuntimeAdapter:
    """Execution boundary implemented by manifest-selected runtimes."""

    def __init__(self, root: Path = ROOT, output_root: Path | None = None) -> None:
        self.root = root
        self.output_root = output_root or root / "artifacts" / "experiments"

    def run(self, manifest: ExperimentManifest, candidate: Any,
            scenario: Any, role: str) -> dict[str, Any]:
        raise NotImplementedError


def _failure(kind: FailureClass, message: str, details: Mapping[str, Any], stage: str) -> dict[str, Any]:
    return {"ok": False, "feedback": Feedback.from_failure(kind, message, details, stage=stage).to_dict()}


class ManifestExtractor:
    def __init__(self, root: Path = ROOT, output_root: Path | None = None) -> None:
        self.root = root
        self.output_root = output_root or root / "artifacts" / "experiments"

    def extract(self, manifest: ExperimentManifest) -> dict[str, Any]:
        out = self.output_root / "evidence"
        out.mkdir(parents=True, exist_ok=True)
        command = ["python3", "-m", "extractor", "bundle", "-s",
                   str(manifest.source.path), "-b", manifest.compile.backend, "-o", str(out)]
        completed = subprocess.run(command, cwd=self.root, text=True,
                                   capture_output=True, check=False)
        if completed.returncode:
            return _failure(FailureClass.EXTRACTION, "evidence extraction failed",
                            {"return_code": completed.returncode, "stderr": completed.stderr[-4000:]}, "extract")
        file_paths = sorted(path for path in out.iterdir() if path.is_file())
        files = [str(path) for path in file_paths]
        digest_builder = hashlib.sha256()
        for path in file_paths:
            digest_builder.update(str(path.relative_to(out)).encode("utf-8"))
            digest_builder.update(b"\0")
            digest_builder.update(path.read_bytes())
        digest = digest_builder.hexdigest()
        return {"ok": True, "value": {"directory": str(out), "files": files, "digest": digest},
                "payload": {"directory": str(out), "files": files, "digest": digest}}


class ManifestCompiler:
    """Compile an adapter-provided candidate using its declared context.

    A context may be a command template.  ``{source}``, ``{module}``, and
    ``{output}`` are substituted from manifest data; no target facts are
    inferred here.  The default context is intentionally fail-closed.
    """
    def __init__(self, root: Path = ROOT, output_root: Path | None = None) -> None:
        self.root = root
        self.output_root = output_root or root / "artifacts" / "experiments"

    def compile(self, manifest: ExperimentManifest, candidate: Any) -> dict[str, Any]:
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("code"), str):
            return _failure(FailureClass.CONTRACT, "candidate does not contain generated code", {}, "compile")
        out_dir = self.output_root / "candidate"
        out = out_dir / f"{manifest.runtime.module}.c"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(candidate["code"], encoding="utf-8")
        try:
            sanitize_source(out, manifest.runtime.safety_policy)
        except (OSError, SafetyPolicyError) as exc:
            return _failure(FailureClass.CONTRACT, "candidate violates safety policy",
                            {"error": str(exc)}, "compile")
        if manifest.trace.instrument:
            instrumented = subprocess.run(
                ["python3", "tools/source/instrument_mmio.py", str(out)],
                cwd=self.root, text=True, capture_output=True, check=False)
            if instrumented.returncode:
                return _failure(FailureClass.INFRASTRUCTURE, "candidate instrumentation failed",
                                {"stderr": instrumented.stderr[-4000:]}, "compile")
        context = manifest.compile.context
        if context.startswith("command:"):
            template = context.removeprefix("command:").strip()
            values = {"source": str(manifest.source.path), "module": manifest.runtime.module,
                      "output": str(out)}
            command = template.format(**values).split()
        elif context == "kbuild":
            (out.parent / "Makefile").write_text(
                f"obj-m += {manifest.runtime.module}.o\n", encoding="utf-8")
            command = ["make", "-C", str(self.root / "platform" / "kernel" / "build"),
                       "M=" + str(out.parent), "modules"]
        else:
            return _failure(FailureClass.INFRASTRUCTURE,
                            "compile context has no configured command", {"context": context}, "compile")
        completed = subprocess.run(command, cwd=self.root, text=True,
                                   capture_output=True, check=False)
        if completed.returncode:
            return _failure(FailureClass.COMPILE, "candidate compilation failed",
                            {"return_code": completed.returncode, "stderr": completed.stderr[-8000:]}, "compile")
        artifact = out.parent / f"{manifest.runtime.module}.ko"
        return {"ok": True, "value": {"path": str(artifact), "source": str(out),
                                        "module": manifest.runtime.module},
                "payload": {"path": str(artifact), "source": str(out),
                            "module": manifest.runtime.module}}


class ManifestContractVerifier:
    """Check Pi receipts against the immutable formal evidence package."""

    def verify(self, manifest: ExperimentManifest, evidence: Any, candidate: Any) -> dict[str, Any]:
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("code"), str):
            return _failure(FailureClass.CONTRACT, "candidate code is missing", {}, "contract")
        if not isinstance(evidence, Mapping) or not isinstance(evidence.get("directory"), str):
            return _failure(FailureClass.INFRASTRUCTURE, "evidence directory is missing", {}, "contract")
        evidence_dir = Path(evidence["directory"])
        formal_paths = sorted(evidence_dir.glob("*.formal.json"))
        if len(formal_paths) != 1:
            return _failure(FailureClass.INFRASTRUCTURE, "formal evidence is ambiguous",
                            {"matches": [str(path) for path in formal_paths]}, "contract")
        try:
            formal = json.loads(formal_paths[0].read_text(encoding="utf-8"))
            report = verify_backend_lowering(formal, candidate["code"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _failure(FailureClass.INFRASTRUCTURE, "contract verification failed",
                            {"error": str(exc)}, "contract")
        if not report.get("complete", False):
            return _failure(FailureClass.CONTRACT, "candidate does not satisfy generation contract",
                            report, "contract")
        return {"ok": True, "value": report, "payload": report}


class QemuRuntimeAdapter(RuntimeAdapter):
    def run(self, manifest: ExperimentManifest, candidate: Any, scenario: Any, role: str) -> dict[str, Any]:
        qemu = manifest.runtime.qemu
        module = qemu.module
        if role == "baseline" and candidate is None:
            baseline_dir = self.root / "artifacts" / "output" / module
            baseline_dir.mkdir(parents=True, exist_ok=True)
            source = baseline_dir / f"{module}.c"
            generated = subprocess.run(
                ["python3", "-m", "extractor", "gen", "-s", str(manifest.source.path),
                 "-b", manifest.compile.backend, "-o", str(source),
                 *(["--manifest", str(manifest.manifest_path)]
                   if manifest.manifest_path is not None else [])],
                cwd=self.root, text=True, capture_output=True, check=False)
            if generated.returncode:
                return _failure(FailureClass.RUNTIME, "baseline source generation failed",
                                {"return_code": generated.returncode, "stderr": generated.stderr[-4000:]}, role)
            if manifest.trace.instrument:
                instrumented = subprocess.run(
                    ["python3", "tools/source/instrument_mmio.py", str(source)],
                    cwd=self.root, text=True, capture_output=True, check=False)
                if instrumented.returncode:
                    return _failure(FailureClass.INFRASTRUCTURE, "baseline instrumentation failed",
                                    {"stderr": instrumented.stderr[-4000:]}, role)
            (baseline_dir / "Makefile").write_text(f"obj-m += {module}.o\n", encoding="utf-8")
            built = subprocess.run(
                ["make", "-C", str(self.root / "platform" / "kernel" / "build"),
                 "M=" + str(baseline_dir), "modules"],
                cwd=self.root, text=True, capture_output=True, check=False)
            if built.returncode:
                return _failure(FailureClass.RUNTIME, "baseline compilation failed",
                                {"return_code": built.returncode, "stderr": built.stderr[-4000:]}, role)
        if isinstance(candidate, Mapping):
            module = str(candidate.get("module", module))
            artifact = candidate.get("path")
            if artifact and role == "candidate":
                destination = self.root / "artifacts" / "output" / module
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(artifact), destination / f"{module}.ko")
        command = ["bash", "scripts/qemu/qemu_run.sh", module,
                   "--bus", qemu.bus,
                   "--machine", qemu.machine,
                   "--timeout", str(qemu.timeout_seconds)]
        if qemu.device:
            command += ["--device", qemu.device]
        if qemu.registrar:
            command += ["--registrar-target", qemu.registrar]
        if manifest.test.executable:
            command += ["--exerciser", str(manifest.test.executable.relative_to(self.root)),
                        "--exerciser-args", " ".join(manifest.test.args)]
        if manifest.test.success_pattern:
            command += ["--success-pattern", manifest.test.success_pattern]
        if qemu.probe_pattern:
            command += ["--probe-pattern", qemu.probe_pattern]
        for argument in qemu.qemu_args:
            command += ["--qemu-arg", argument]
        completed = subprocess.run(command, cwd=self.root, text=True,
                                   capture_output=True, check=False)
        trace_path = self.output_root / f"{role}.trace"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            return _failure(FailureClass.RUNTIME, "runtime adapter failed",
                            {"role": role, "return_code": completed.returncode,
                             "trace": str(trace_path)}, role)
        return {"ok": True, "value": str(trace_path),
                "payload": {"role": role, "trace": str(trace_path)}}


RUNTIME_ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    "qemu": QemuRuntimeAdapter,
    "qemu-pci": QemuRuntimeAdapter,
    "qemu-platform": QemuRuntimeAdapter,
}


def register_runtime_adapter(adapter_id: str, implementation: type[RuntimeAdapter], *, replace: bool = False) -> None:
    """Register an adapter implementation for manifest dispatch.

    Registration is explicit so adding a new runtime does not require adding
    device-specific branches to the orchestration path.
    """
    if not isinstance(adapter_id, str) or not adapter_id.strip():
        raise ValueError("runtime adapter id must be a non-empty string")
    if not isinstance(implementation, type) or not issubclass(implementation, RuntimeAdapter):
        raise TypeError("runtime adapter implementation must subclass RuntimeAdapter")
    if adapter_id in RUNTIME_ADAPTERS and not replace:
        raise ValueError(f"runtime adapter already registered: {adapter_id}")
    RUNTIME_ADAPTERS[adapter_id] = implementation


def resolve_runtime_adapter(adapter_id: str, root: Path = ROOT,
                            output_root: Path | None = None,
                            registry: Mapping[str, type[RuntimeAdapter]] | None = None) -> RuntimeAdapter:
    """Instantiate the implementation selected by ``runtime.adapter``."""
    adapters = RUNTIME_ADAPTERS if registry is None else registry
    try:
        implementation = adapters[adapter_id]
    except (KeyError, TypeError) as exc:
        available = ", ".join(sorted(adapters))
        raise RuntimeAdapterError(
            f"unknown runtime adapter {adapter_id!r}; available adapters: {available}"
        ) from exc
    if not isinstance(implementation, type) or not issubclass(implementation, RuntimeAdapter):
        raise RuntimeAdapterError(f"runtime adapter {adapter_id!r} has an invalid implementation")
    return implementation(root, output_root)


class ManifestRuntime:
    """Dispatch runtime execution to the implementation named by a manifest."""

    def __init__(self, root: Path = ROOT, output_root: Path | None = None,
                 registry: Mapping[str, type[RuntimeAdapter]] | None = None) -> None:
        self.root = root
        self.output_root = output_root or root / "artifacts" / "experiments"
        self.registry = registry

    def run(self, manifest: ExperimentManifest, candidate: Any, scenario: Any, role: str) -> dict[str, Any]:
        adapter = resolve_runtime_adapter(manifest.runtime.adapter, self.root,
                                          self.output_root, self.registry)
        return adapter.run(manifest, candidate, scenario, role)


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
    def __init__(self, root: Path = ROOT, output_root: Path | None = None) -> None:
        self.extractor = ManifestExtractor(root, output_root)
        self.pi = SubprocessPiBridge(str(root / "tools" / "pi" / "pi_synth.sh"))
        self.compiler = ManifestCompiler(root, output_root)
        self.contract = ManifestContractVerifier()
        self.runtime = ManifestRuntime(root, output_root)
        self.comparator = ManifestComparator()


def build_adapters(manifest: ExperimentManifest | None = None,
                   output_dir: str | Path | None = None) -> Adapters:
    output_root = Path(output_dir) if output_dir is not None else None
    if output_root is None and manifest is not None:
        output_root = ROOT / "artifacts" / "experiments" / manifest.name
    return Adapters(output_root=output_root)
