from __future__ import annotations

import json
from pathlib import Path

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from experiment_manifest import validate_manifest  # noqa: E402
from experiment_protocol import FailureClass, Feedback  # noqa: E402
from experiment_runner import AdapterResult, ExperimentRunner  # noqa: E402


def manifest(**limits):
    root = Path(__file__).resolve().parents[2]
    document = {
        "schema": 1, "name": "fake", "source": {"path": "README.md"},
        "compile": {"backend": "fake", "language": "c", "context": "test"},
        "runtime": {"adapter": "fake", "machine": "test", "device": "test",
                     "bus": "none", "module": "test", "timeout_seconds": 1},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 3, "runtime": 3, "trace": 3, **limits},
    }
    return validate_manifest(document, repo_root=root)


class Fake:
    def __init__(self, *, compile_fail=0, runtime_fail=0, mismatch=0, extraction=None):
        self.events = []
        self.compile_fail = compile_fail
        self.runtime_fail = runtime_fail
        self.mismatch = mismatch
        self.extraction = extraction

    def extract(self, m):
        self.events.append("extract")
        if self.extraction:
            return AdapterResult.failure(Feedback.from_failure(FailureClass.EXTRACTION, self.extraction, {}))
        return AdapterResult.success({"ris": []})

    def synthesize(self, m, evidence, feedback=None, candidate=None):
        self.events.append("repair" if feedback else "synthesize")
        return AdapterResult.success({"code": len(self.events)}, {"scenario": [{"name": "probe"}]})

    def compile(self, m, candidate):
        self.events.append("compile")
        if self.compile_fail:
            self.compile_fail -= 1
            return AdapterResult.failure(Feedback.from_failure(FailureClass.COMPILE, "compile failed", {"stderr": "bad"}))
        return AdapterResult.success({"artifact": "candidate.ko"})

    def run(self, m, candidate, scenario, role):
        self.events.append(role)
        if self.runtime_fail:
            self.runtime_fail -= 1
            return AdapterResult.failure(Feedback.from_failure(FailureClass.RUNTIME, "runtime failed", {"role": role}))
        return AdapterResult.success({"role": role, "events": [1]})

    def compare(self, m, baseline, candidate):
        self.events.append("compare")
        if self.mismatch:
            self.mismatch -= 1
            return {"equal": False, "reason": "event_mismatch"}
        return {"equal": True}


class RejectingContract:
    def verify(self, m, evidence, candidate):
        return AdapterResult.failure(Feedback.from_failure(
            FailureClass.CONTRACT, "missing receipt", {"candidate": candidate}))


def run(tmp_path, fake, **limits):
    runner = ExperimentRunner(extractor=fake, pi=fake, compiler=fake,
                              runtime=fake, comparator=fake)
    return runner.run(manifest(**limits), output_dir=tmp_path)


def test_stage_order_and_append_only_records(tmp_path):
    fake = Fake()
    result = run(tmp_path, fake)
    assert result.accepted
    assert fake.events == ["extract", "synthesize", "compile", "baseline", "candidate", "compare"]
    assert [record.stage for record in result.records] == fake.events
    assert (tmp_path / "experiment.json").is_file()
    files = sorted((tmp_path / "iterations").glob("*.json"))
    assert len(files) == len(result.records)
    assert json.loads(files[-1].read_text())["status"] == "passed"


def test_compile_retry_sends_structured_feedback(tmp_path):
    fake = Fake(compile_fail=1)
    result = run(tmp_path, fake)
    assert result.accepted
    assert fake.events == ["extract", "synthesize", "compile", "repair", "compile", "baseline", "candidate", "compare"]


def test_runtime_retry(tmp_path):
    fake = Fake(runtime_fail=1)
    result = run(tmp_path, fake)
    assert result.accepted
    assert fake.events.count("repair") == 1
    assert fake.events[-4:] == ["repair", "compile", "baseline", "candidate"] or "compare" in fake.events[-1:]


def test_trace_retry(tmp_path):
    fake = Fake(mismatch=1)
    result = run(tmp_path, fake)
    assert result.accepted
    assert "repair" in fake.events
    assert [record.stage for record in result.records].count("compare") == 2


@pytest.mark.parametrize("kwargs,stage", [({"compile_fail": 4}, "compile"), ({"mismatch": 4}, "compare")])
def test_exhausted_limit_is_rejected(tmp_path, kwargs, stage):
    fake = Fake(**kwargs)
    result = run(tmp_path, fake, compile=2, trace=2)
    assert not result.accepted
    assert result.failure is not None
    assert result.failure.failure_class in {FailureClass.COMPILE, FailureClass.TRACE}


def test_extraction_and_infrastructure_fail_closed(tmp_path):
    fake = Fake(extraction="unreadable source")
    result = run(tmp_path, fake)
    assert not result.accepted
    assert result.failure.failure_class is FailureClass.EXTRACTION
    assert fake.events == ["extract"]


def test_unexpected_adapter_exception_is_infrastructure_failure(tmp_path):
    fake = Fake()
    def broken_compile(*args):
        raise OSError("tool missing")
    fake.compile = broken_compile
    result = run(tmp_path, fake)
    assert not result.accepted
    assert result.failure.failure_class is FailureClass.INFRASTRUCTURE
    assert result.failure.stage == "compile"


def test_contract_verifier_runs_before_compile_and_fails_closed(tmp_path):
    fake = Fake()
    runner = ExperimentRunner(extractor=fake, pi=fake, compiler=fake,
                              runtime=fake, comparator=fake,
                              contract=RejectingContract())
    result = runner.run(manifest(), output_dir=tmp_path)
    assert not result.accepted
    assert result.failure.failure_class is FailureClass.CONTRACT
    assert fake.events == ["extract", "synthesize"]
