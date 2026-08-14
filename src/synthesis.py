"""Bundle assembly for LLM synthesis.

Assembles the reharness extraction output (.ris/.dspec/DeviceSpec JSON/
.bind/.facts/score.txt)
into a directory for the TS+Pi synthesizer to consume. The LLM synthesis itself
is handled by ``tools/pi/synth.mjs``; the compile/QEMU/trace iteration loop is
handled by ``scripts/e2e/run_e2e.sh``. This module is purely the Python-side
bundle packager.
"""
from __future__ import annotations
import json
import os
import subprocess
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from extractor.formalize import save_formal_text
from extractor.spec import default_bind, device_spec_to_dict
from extractor.metrics import score as score_fn
from verification.backend_lowering_oracle import build_generation_contract


_PROTOCOL_VERSION = 1


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a SHA-256 digest") from exc
    return value.lower()


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


@dataclass(frozen=True)
class PiRequest:
    """Versioned, target-neutral message sent to the Pi synthesis bridge."""

    operation: str
    manifest_digest: str
    evidence_digest: str
    evidence: Mapping[str, Any]
    candidate: Any = None
    feedback: Mapping[str, Any] | None = None
    remaining_budget: Mapping[str, Any] | None = None
    protocol_version: int = _PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int) or self.protocol_version != _PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol_version: {self.protocol_version}")
        if self.operation not in {"synthesize", "repair"}:
            raise ValueError("operation must be synthesize or repair")
        object.__setattr__(self, "manifest_digest", _digest(self.manifest_digest, "manifest_digest"))
        object.__setattr__(self, "evidence_digest", _digest(self.evidence_digest, "evidence_digest"))
        object.__setattr__(self, "evidence", _object(self.evidence, "evidence"))
        if self.candidate is not None:
            try:
                json.dumps(self.candidate)
            except TypeError as exc:
                raise ValueError("candidate must be JSON-serializable") from exc
        if self.feedback is not None:
            object.__setattr__(self, "feedback", _object(self.feedback, "feedback"))
        if self.remaining_budget is not None:
            object.__setattr__(self, "remaining_budget", _object(self.remaining_budget, "remaining_budget"))
        if self.operation == "repair" and self.feedback is None:
            raise ValueError("repair request requires feedback")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "operation": self.operation,
            "manifest_digest": self.manifest_digest,
            "evidence_digest": self.evidence_digest,
            "evidence": dict(self.evidence),
        }
        if self.candidate is not None:
            result["candidate"] = self.candidate
        if self.feedback is not None:
            result["feedback"] = dict(self.feedback)
        if self.remaining_budget is not None:
            result["remaining_budget"] = dict(self.remaining_budget)
        return result

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "PiRequest":
        if not isinstance(document, Mapping):
            raise ValueError("request must be an object")
        allowed = {"protocol_version", "operation", "manifest_digest", "evidence_digest",
                   "evidence", "candidate", "feedback", "remaining_budget"}
        extra = sorted(set(document) - allowed)
        if extra:
            raise ValueError(f"request contains unknown field(s): {', '.join(extra)}")
        required = {"protocol_version", "operation", "manifest_digest", "evidence_digest", "evidence"}
        missing = sorted(required - set(document))
        if missing:
            raise ValueError(f"request missing required field(s): {', '.join(missing)}")
        return cls(**dict(document))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class PiResponse:
    """Stable response envelope; model prose is retained only as diagnostics."""

    ok: bool
    code: str | None = None
    scenario: Sequence[Mapping[str, Any]] | None = None
    diagnostics: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None
    protocol_version: int = _PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int) or self.protocol_version != _PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol_version: {self.protocol_version}")
        if not isinstance(self.ok, bool):
            raise ValueError("ok must be boolean")
        if self.ok and (not isinstance(self.code, str) or not self.code.strip()):
            raise ValueError("successful response requires non-empty code")
        if not self.ok and self.error is None:
            raise ValueError("failed response requires error")
        if self.scenario is not None:
            if not isinstance(self.scenario, Sequence) or isinstance(self.scenario, (str, bytes)):
                raise ValueError("scenario must be an array")
            if any(not isinstance(item, Mapping) for item in self.scenario):
                raise ValueError("scenario entries must be objects")
            object.__setattr__(self, "scenario", tuple(dict(item) for item in self.scenario))
        for field in ("diagnostics", "error"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _object(value, field))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"protocol_version": self.protocol_version, "ok": self.ok}
        if self.code is not None:
            result["code"] = self.code
        if self.scenario is not None:
            result["scenario"] = [dict(item) for item in self.scenario]
        if self.diagnostics is not None:
            result["diagnostics"] = dict(self.diagnostics)
        if self.error is not None:
            result["error"] = dict(self.error)
        return result

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "PiResponse":
        if not isinstance(document, Mapping):
            raise ValueError("response must be an object")
        allowed = {"protocol_version", "ok", "code", "scenario", "diagnostics", "error"}
        extra = sorted(set(document) - allowed)
        if extra:
            raise ValueError(f"response contains unknown field(s): {', '.join(extra)}")
        for field in ("protocol_version", "ok"):
            if field not in document:
                raise ValueError(f"response missing required field: {field}")
        return cls(**dict(document))


def parse_pi_response(payload: str | bytes | Mapping[str, Any]) -> PiResponse:
    """Parse and validate a bridge response; malformed output is never accepted."""
    if isinstance(payload, Mapping):
        document = payload
    else:
        try:
            document = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Pi response is not valid JSON") from exc
    return PiResponse.from_dict(document)


def render_pi_prompt(request: PiRequest) -> str:
    """Render a generic prompt from the envelope without target-specific policy."""
    body = json.dumps(request.to_dict(), indent=2, sort_keys=True)
    return ("Produce a target implementation from the supplied evidence package. "
            "Return the implementation in a fenced C code block. If a test scenario "
            "is needed, return one JSON object in a fenced json block with a `scenario` array. "
            "Treat repair feedback as authoritative and preserve the register contract.\n\n"
            "REQUEST ENVELOPE:\n```json\n" + body + "\n```\n")


class SubprocessPiBridge:
    """PiBridge adapter speaking the JSON envelope over ``pi_synth.sh``."""

    def __init__(self, command: str | Sequence[str] = "tools/pi/pi_synth.sh", *, timeout: int = 600):
        self.command = (command,) if isinstance(command, str) else tuple(command)
        self.timeout = timeout

    def synthesize(self, manifest: Any, evidence: Any, feedback: Any = None,
                   candidate: Any = None) -> dict[str, Any]:
        manifest_digest = getattr(manifest, "digest", None)
        if not isinstance(manifest_digest, str):
            raise ValueError("manifest must expose a digest")
        evidence_dict = evidence.to_dict() if hasattr(evidence, "to_dict") else _object(evidence, "evidence")
        evidence_digest = hashlib.sha256(
            json.dumps(evidence_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        feedback_dict = feedback.to_dict() if hasattr(feedback, "to_dict") else feedback
        limits = getattr(manifest, "limits", None)
        remaining_budget = limits.to_dict() if hasattr(limits, "to_dict") else None
        request = PiRequest("repair" if feedback_dict else "synthesize", manifest_digest,
                            evidence_digest, evidence_dict, candidate,
                            feedback_dict, remaining_budget)
        completed = subprocess.run(self.command, input=request.to_json() + "\n", text=True,
                                   capture_output=True, timeout=self.timeout, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Pi bridge failed")
        response = parse_pi_response(completed.stdout)
        if not response.ok:
            raise RuntimeError((response.error or {}).get("message", "Pi synthesis failed"))
        return {"code": response.code, "scenario": response.scenario or [],
                "diagnostics": response.diagnostics or {}}


def build_bundle(res, backend: str, outdir: str) -> str:
    """Assemble the LLM input bundle: RIS, DeviceSpec, bind, facts, score.
    Returns the bundle directory path."""
    os.makedirs(outdir, exist_ok=True)
    name = res.formal["driver"]
    bind = default_bind(res.device_spec, backend)
    generation_contract = build_generation_contract(res.formal)
    generation_contract["synthesis_readiness"] = score_fn(
        res.device_spec, res.formal, res.warnings, res.facts)

    save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
    _w(outdir, f"{name}.formal.json", json.dumps(
        res.formal, indent=2, sort_keys=True))
    _w(outdir, "generation-contract.json", json.dumps(
        generation_contract, indent=2, sort_keys=True))
    _w(outdir, f"{name}.dspec", res.device_spec.display())
    _w(outdir, f"{name}.device-spec.json", json.dumps(
        device_spec_to_dict(res.device_spec), indent=2, sort_keys=True))
    _w(outdir, f"{name}.{backend}.bind", bind.display())
    _w(outdir, f"{name}.facts", res.facts.display())
    _w(outdir, "score.txt", generation_contract[
        "synthesis_readiness"].__repr__())
    return outdir


def _w(outdir: str, name: str, text: str):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")


def run_pi_synth(input_text: str, *, timeout: int = 600) -> str:
    """Run pi_synth.sh with arbitrary stdin and return stdout.

    This is the single subprocess entry point for all Pi bridge calls.
    Both text-mode (generator) and JSON-envelope (synthesis) callers
    go through this function.
    """
    root = Path(__file__).resolve().parent
    script = root / "tools" / "pi" / "pi_synth.sh"
    # Fallback: tools/ may be alongside src/
    if not script.exists():
        script = root.parent / "tools" / "pi" / "pi_synth.sh"
    completed = subprocess.run(
        [str(script)], input=input_text,
        capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Pi bridge failed")
    return completed.stdout
