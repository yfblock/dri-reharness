from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.source.sanitize import SafetyPolicyError, sanitize_text
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
