from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.source.sanitize import SafetyPolicyError, sanitize_text
from tools.source.sanitize import sanitize_source
from experiment_manifest import SafetyPolicy


def test_sanitizer_rejects_configured_forbidden_token():
    policy = SafetyPolicy(forbidden_tokens=("FORBIDDEN_OP",), action="reject")
    with pytest.raises(SafetyPolicyError, match="FORBIDDEN_OP"):
        sanitize_text("void f(void) { FORBIDDEN_OP(); }\n", policy)


def test_sanitizer_rewrites_only_manifest_patterns():
    policy = SafetyPolicy(
        forbidden_tokens=("FORBIDDEN_OP",),
        action="rewrite",
        rewrite_rules=({"pattern": r"^[^\n]*FORBIDDEN_OP[^\n]*\n", "replacement": ""},),
    )
    updated, observed = sanitize_text(
        "keep();\nFORBIDDEN_OP();\n", policy)
    assert observed == ("FORBIDDEN_OP",)
    assert updated == "keep();\n"


def test_sanitizer_allows_source_without_policy_tokens():
    policy = SafetyPolicy(forbidden_tokens=("FORBIDDEN_OP",), action="reject")
    assert sanitize_text("keep();\n", policy) == ("keep();\n", ())


def test_generic_sanitizer_has_no_target_vocabulary():
    text = Path("tools/source/sanitize.py").read_text(encoding="utf-8")
    assert "IO_DMA_CMD" not in text
    assert "DMA_IRQ" not in text


def test_sanitizer_writes_a_hash_bound_receipt(tmp_path):
    source = tmp_path / "driver.c"
    receipt = tmp_path / "safety.json"
    source.write_text("keep();\nFORBIDDEN_OP();\n", encoding="utf-8")
    policy = SafetyPolicy(
        forbidden_tokens=("FORBIDDEN_OP",), action="rewrite",
        rewrite_rules=({"pattern": r"^[^\n]*FORBIDDEN_OP[^\n]*\n", "replacement": ""},),
    )

    sanitize_source(source, policy, receipt_path=receipt)

    import json
    document = json.loads(receipt.read_text(encoding="utf-8"))
    assert document["schema"] == 1
    assert document["matched_tokens"] == ["FORBIDDEN_OP"]
    assert document["source_before_sha256"] != document["source_after_sha256"]
    assert document["policy_digest"]
