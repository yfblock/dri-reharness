"""Generic, manifest-driven closed-loop experiment runner.

The runner owns stage ordering and persistence.  Device facts and command
output interpretation belong to adapters supplied by the caller; this module
contains no target-specific knowledge.
"""
from __future__ import annotations

from dataclasses import dataclass, is_dataclass, asdict
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from experiment_manifest import ExperimentManifest, load_manifest
from experiment_protocol import FailureClass, Feedback, StageRecord


class Adapter(Protocol):
    """Marker protocol for injected adapters."""


class Extractor(Adapter, Protocol):
    def extract(self, manifest: ExperimentManifest) -> Any: ...


class PiBridge(Adapter, Protocol):
    def synthesize(self, manifest: ExperimentManifest, evidence: Any,
                   feedback: Feedback | None = None, candidate: Any = None) -> Any: ...


class Compiler(Adapter, Protocol):
    def compile(self, manifest: ExperimentManifest, candidate: Any) -> Any: ...


class ContractVerifier(Adapter, Protocol):
    def verify(self, manifest: ExperimentManifest, evidence: Any, candidate: Any) -> Any: ...


class RuntimeRunner(Adapter, Protocol):
    def run(self, manifest: ExperimentManifest, candidate: Any, scenario: Any,
            role: str) -> Any: ...


class TraceComparator(Adapter, Protocol):
    def compare(self, manifest: ExperimentManifest, baseline: Any, candidate: Any) -> Any: ...


@dataclass(frozen=True)
class AdapterResult:
    """Stable adapter boundary used by the runner and test fakes."""

    ok: bool
    value: Any = None
    payload: Mapping[str, Any] | None = None
    feedback: Feedback | None = None

    @classmethod
    def success(cls, value: Any = None, payload: Mapping[str, Any] | None = None) -> "AdapterResult":
        return cls(True, value, payload)

    @classmethod
    def failure(cls, feedback: Feedback, payload: Mapping[str, Any] | None = None) -> "AdapterResult":
        return cls(False, None, payload, feedback)


@dataclass(frozen=True)
class ExperimentResult:
    accepted: bool
    status: str
    output_dir: Path
    records: tuple[StageRecord, ...]
    failure: Feedback | None = None
    candidate: Any = None
    comparison: Any = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Feedback):
        return value.to_dict()
    if isinstance(value, StageRecord):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable(vars(value))
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _feedback(value: Any, failure_class: FailureClass, stage: str, iteration: int) -> Feedback:
    if isinstance(value, Feedback):
        if value.stage is not None and value.iteration is not None:
            return value
        return Feedback(value.failure_class, value.message, value.details,
                        value.retryable, value.stage or stage, value.iteration or iteration)
    if isinstance(value, Mapping):
        try:
            parsed = Feedback.from_dict(value)
            if parsed.stage is None or parsed.iteration is None:
                return Feedback(parsed.failure_class, parsed.message, parsed.details,
                                parsed.retryable, parsed.stage or stage, parsed.iteration or iteration)
            return parsed
        except (TypeError, ValueError):
            message = str(value.get("message", value.get("error", "adapter failure")))
            details = dict(value)
    else:
        message = str(value or "adapter failure")
        details = {}
    return Feedback.from_failure(failure_class, message, details, stage=stage, iteration=iteration)


def _coerce(raw: Any, failure_class: FailureClass, stage: str, iteration: int) -> AdapterResult:
    if isinstance(raw, AdapterResult):
        if raw.ok:
            return raw
        feedback = _feedback(raw.feedback or raw.payload, failure_class, stage, iteration)
        return AdapterResult.failure(feedback, raw.payload)
    if isinstance(raw, Feedback):
        return AdapterResult.failure(_feedback(raw, failure_class, stage, iteration))
    if raw is None:
        return AdapterResult.failure(_feedback("adapter returned no result", failure_class, stage, iteration))
    if isinstance(raw, bool):
        return (AdapterResult.success(True) if raw else
                AdapterResult.failure(_feedback("adapter reported failure", failure_class, stage, iteration)))
    if isinstance(raw, Mapping):
        marker = raw.get("ok", raw.get("success"))
        if marker is False:
            return AdapterResult.failure(_feedback(raw.get("feedback", raw), failure_class, stage, iteration), raw)
        if marker is True:
            payload = raw.get("payload", raw)
            return AdapterResult.success(raw.get("value", payload), payload if isinstance(payload, Mapping) else None)
    return AdapterResult.success(raw)


def _invoke(function: Any, *args: Any, failure_class: FailureClass,
            stage: str, iteration: int, **kwargs: Any) -> AdapterResult:
    """Call an adapter and convert unexpected exceptions to infrastructure feedback."""
    try:
        raw = function(*args, **kwargs)
    except Exception as exc:  # adapters own subprocess details; runner fails closed
        feedback = Feedback.from_failure(
            FailureClass.INFRASTRUCTURE, f"{stage} adapter failed: {exc}",
            {"exception": type(exc).__name__}, stage=stage, iteration=iteration,
        )
        return AdapterResult.failure(feedback)
    return _coerce(raw, failure_class, stage, iteration)


class ExperimentRunner:
    """Execute the closed-loop state machine with injected adapters."""

    def __init__(self, *, extractor: Extractor, pi: PiBridge, compiler: Compiler,
                 runtime: RuntimeRunner, comparator: TraceComparator,
                 contract: ContractVerifier | None = None,
                 output_root: str | Path = "artifacts/experiments") -> None:
        self.extractor = extractor
        self.pi = pi
        self.compiler = compiler
        self.contract = contract
        self.runtime = runtime
        self.comparator = comparator
        self.output_root = Path(output_root)

    def run(self, manifest: ExperimentManifest | str | Path, *, output_dir: str | Path | None = None) -> ExperimentResult:
        if not isinstance(manifest, ExperimentManifest):
            manifest = load_manifest(manifest)
        out = Path(output_dir) if output_dir is not None else self.output_root / manifest.name
        out.mkdir(parents=True, exist_ok=True)
        iterations = out / "iterations"
        iterations.mkdir(exist_ok=True)
        records: list[StageRecord] = []
        state: dict[str, Any] = {"schema": 1, "name": manifest.name,
                                 "manifest_digest": manifest.digest,
                                 "manifest": manifest.to_dict(), "status": "running"}
        self._persist(out, state, records)

        evidence_digest: str | None = None

        def record(stage: str, iteration: int, status: str, payload: Any = None,
                   feedback: Feedback | None = None) -> None:
            merged: dict[str, Any] = {}
            if payload is not None:
                merged["result"] = _jsonable(payload)
            if feedback is not None:
                merged["feedback"] = feedback.to_dict()
            item = StageRecord(stage, iteration, status, manifest.digest,
                               evidence_digest=evidence_digest, payload=merged or None)
            records.append(item)
            path = iterations / f"{len(records):02d}-{stage}.json"
            path.write_text(json.dumps(item.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self._persist(out, state, records)

        def stop(feedback: Feedback, *, status: str = "failed", candidate: Any = None,
                 comparison: Any = None) -> ExperimentResult:
            state.update({"status": status, "accepted": False, "failure": feedback.to_dict()})
            self._persist(out, state, records)
            return ExperimentResult(False, status, out, tuple(records), feedback, candidate, comparison)

        extraction = _invoke(self.extractor.extract, manifest, failure_class=FailureClass.EXTRACTION, stage="extract", iteration=1)
        if not extraction.ok:
            record("extract", 1, "failed", feedback=extraction.feedback)
            return stop(extraction.feedback or _feedback("extraction failed", FailureClass.EXTRACTION, "extract", 1))
        evidence = extraction.value
        if extraction.payload and isinstance(extraction.payload.get("digest"), str):
            evidence_digest = extraction.payload["digest"]
        elif isinstance(evidence, Mapping) and isinstance(evidence.get("digest"), str):
            evidence_digest = evidence["digest"]
        record("extract", 1, "passed", extraction.payload or evidence)

        synthesis = _invoke(self.pi.synthesize, manifest, evidence, failure_class=FailureClass.CONTRACT, stage="synthesize", iteration=1)
        if not synthesis.ok:
            record("synthesize", 1, "failed", feedback=synthesis.feedback)
            return stop(synthesis.feedback or _feedback("synthesis failed", FailureClass.CONTRACT, "synthesize", 1))
        candidate = synthesis.value
        scenario = synthesis.payload.get("scenario") if synthesis.payload else None
        if scenario is None and isinstance(candidate, Mapping):
            scenario = candidate.get("scenario")
        record("synthesize", 1, "passed", synthesis.payload or candidate)

        checked = self._verify_contract(manifest, evidence, candidate, 1)
        if not checked.ok:
            record("contract", 1, "failed", feedback=checked.feedback)
            return stop(checked.feedback or _feedback("candidate contract rejected",
                                                       FailureClass.CONTRACT, "contract", 1),
                        candidate=candidate)
        if checked.value is not None:
            record("contract", 1, "passed", checked.payload or checked.value)

        total = manifest.limits.total
        used = 0
        compile_attempts = runtime_attempts = trace_attempts = 0
        last_comparison: Any = None
        while True:
            used += 1
            if total is not None and used > total:
                feedback = _feedback("total iteration limit exhausted", FailureClass.CONTRACT, "repair", used)
                record("repair", used, "failed", feedback=feedback)
                return stop(feedback, candidate=candidate, comparison=last_comparison)
            compile_attempts += 1
            compiled = _invoke(self.compiler.compile, manifest, candidate, failure_class=FailureClass.COMPILE, stage="compile", iteration=used)
            if not compiled.ok:
                record("compile", used, "failed", feedback=compiled.feedback)
                if compiled.feedback and compiled.feedback.failure_class is FailureClass.INFRASTRUCTURE:
                    return stop(compiled.feedback, candidate=candidate)
                if compile_attempts >= manifest.limits.compile:
                    return stop(compiled.feedback or _feedback("compile limit exhausted", FailureClass.COMPILE, "compile", used), candidate=candidate)
                repair = self._repair(manifest, evidence, candidate, compiled.feedback, used)
                if not repair.ok:
                    record("repair", used, "failed", feedback=repair.feedback)
                    return stop(repair.feedback or _feedback("repair failed", FailureClass.CONTRACT, "repair", used), candidate=candidate)
                candidate = repair.value
                scenario = repair.payload.get("scenario", scenario) if repair.payload else scenario
                record("repair", used, "passed", repair.payload or candidate)
                checked = self._verify_contract(manifest, evidence, candidate, used)
                if not checked.ok:
                    record("contract", used, "failed", feedback=checked.feedback)
                    return stop(checked.feedback or _feedback("candidate contract rejected",
                                                               FailureClass.CONTRACT, "contract", used),
                                candidate=candidate)
                if checked.value is not None:
                    record("contract", used, "passed", checked.payload or checked.value)
                continue
            compile_attempts = 0
            record("compile", used, "passed", compiled.payload or compiled.value)

            baseline = _invoke(self.runtime.run, manifest, None, scenario, "baseline", failure_class=FailureClass.RUNTIME, stage="baseline", iteration=used)
            if not baseline.ok:
                record("baseline", used, "failed", feedback=baseline.feedback)
                if baseline.feedback and baseline.feedback.failure_class is FailureClass.INFRASTRUCTURE:
                    return stop(baseline.feedback, candidate=candidate)
                runtime_attempts += 1
                if runtime_attempts >= manifest.limits.runtime:
                    return stop(baseline.feedback or _feedback("baseline runtime failed", FailureClass.RUNTIME, "baseline", used), candidate=candidate)
                repair = self._repair(manifest, evidence, candidate, baseline.feedback, used)
                if not repair.ok:
                    record("repair", used, "failed", feedback=repair.feedback)
                    return stop(repair.feedback or _feedback("repair failed", FailureClass.CONTRACT, "repair", used), candidate=candidate)
                candidate, scenario = repair.value, (repair.payload.get("scenario", scenario) if repair.payload else scenario)
                record("repair", used, "passed", repair.payload or candidate)
                checked = self._verify_contract(manifest, evidence, candidate, used)
                if not checked.ok:
                    record("contract", used, "failed", feedback=checked.feedback)
                    return stop(checked.feedback or _feedback("candidate contract rejected",
                                                               FailureClass.CONTRACT, "contract", used),
                                candidate=candidate)
                if checked.value is not None:
                    record("contract", used, "passed", checked.payload or checked.value)
                continue
            record("baseline", used, "passed", baseline.payload or baseline.value)
            candidate_artifact = compiled.value
            candidate_run = _invoke(self.runtime.run, manifest, candidate_artifact, scenario, "candidate", failure_class=FailureClass.RUNTIME, stage="candidate", iteration=used)
            if not candidate_run.ok:
                record("candidate", used, "failed", feedback=candidate_run.feedback)
                if candidate_run.feedback and candidate_run.feedback.failure_class is FailureClass.INFRASTRUCTURE:
                    return stop(candidate_run.feedback, candidate=candidate)
                runtime_attempts += 1
                if runtime_attempts >= manifest.limits.runtime:
                    return stop(candidate_run.feedback or _feedback("candidate runtime failed", FailureClass.RUNTIME, "candidate", used), candidate=candidate)
                repair = self._repair(manifest, evidence, candidate, candidate_run.feedback, used)
                if not repair.ok:
                    record("repair", used, "failed", feedback=repair.feedback)
                    return stop(repair.feedback or _feedback("repair failed", FailureClass.CONTRACT, "repair", used), candidate=candidate)
                candidate, scenario = repair.value, (repair.payload.get("scenario", scenario) if repair.payload else scenario)
                record("repair", used, "passed", repair.payload or candidate)
                checked = self._verify_contract(manifest, evidence, candidate, used)
                if not checked.ok:
                    record("contract", used, "failed", feedback=checked.feedback)
                    return stop(checked.feedback or _feedback("candidate contract rejected",
                                                               FailureClass.CONTRACT, "contract", used),
                                candidate=candidate)
                if checked.value is not None:
                    record("contract", used, "passed", checked.payload or checked.value)
                continue
            record("candidate", used, "passed", candidate_run.payload or candidate_run.value)
            runtime_attempts = 0

            comparison = _invoke(self.comparator.compare, manifest, baseline.value, candidate_run.value, failure_class=FailureClass.TRACE, stage="compare", iteration=used)
            last_comparison = comparison.value
            if comparison.ok and self._comparison_equal(comparison.value):
                record("compare", used, "passed", comparison.payload or comparison.value)
                state.update({"status": "accepted", "accepted": True})
                self._persist(out, state, records)
                return ExperimentResult(True, "accepted", out, tuple(records), candidate=candidate, comparison=comparison.value)
            feedback = comparison.feedback or _feedback("trace mismatch", FailureClass.TRACE, "compare", used)
            record("compare", used, "failed", comparison.payload or comparison.value, feedback)
            if feedback.failure_class is FailureClass.INFRASTRUCTURE:
                return stop(feedback, candidate=candidate, comparison=comparison.value)
            trace_attempts += 1
            if trace_attempts >= manifest.limits.trace:
                return stop(feedback, candidate=candidate, comparison=comparison.value)
            repair = self._repair(manifest, evidence, candidate, feedback, used)
            if not repair.ok:
                record("repair", used, "failed", feedback=repair.feedback)
                return stop(repair.feedback or _feedback("repair failed", FailureClass.CONTRACT, "repair", used), candidate=candidate, comparison=comparison.value)
            candidate, scenario = repair.value, (repair.payload.get("scenario", scenario) if repair.payload else scenario)
            record("repair", used, "passed", repair.payload or candidate)
            checked = self._verify_contract(manifest, evidence, candidate, used)
            if not checked.ok:
                record("contract", used, "failed", feedback=checked.feedback)
                return stop(checked.feedback or _feedback("candidate contract rejected",
                                                           FailureClass.CONTRACT, "contract", used),
                            candidate=candidate, comparison=comparison.value)
            if checked.value is not None:
                record("contract", used, "passed", checked.payload or checked.value)

    def _repair(self, manifest: ExperimentManifest, evidence: Any, candidate: Any,
                feedback: Feedback | None, iteration: int) -> AdapterResult:
        method = getattr(self.pi, "repair", None)
        if callable(method):
            return _invoke(method, manifest, evidence, candidate, feedback,
                           failure_class=FailureClass.CONTRACT, stage="repair", iteration=iteration)
        return _invoke(self.pi.synthesize, manifest, evidence,
                       feedback=feedback, candidate=candidate,
                       failure_class=FailureClass.CONTRACT, stage="repair", iteration=iteration)

    def _verify_contract(self, manifest: ExperimentManifest, evidence: Any,
                         candidate: Any, iteration: int) -> AdapterResult:
        if self.contract is None:
            return AdapterResult.success()
        return _invoke(self.contract.verify, manifest, evidence, candidate,
                       failure_class=FailureClass.CONTRACT, stage="contract",
                       iteration=iteration)

    @staticmethod
    def _comparison_equal(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, Mapping):
            return bool(value.get("equal", value.get("ok", False)))
        return bool(getattr(value, "equal", False))

    @staticmethod
    def _persist(out: Path, state: Mapping[str, Any], records: Sequence[StageRecord]) -> None:
        document = dict(state)
        document["records"] = [item.to_dict() for item in records]
        (out / "experiment.json").write_text(json.dumps(_jsonable(document), indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = ["AdapterResult", "ExperimentResult", "ExperimentRunner", "Extractor", "PiBridge", "Compiler", "ContractVerifier", "RuntimeRunner", "TraceComparator"]
