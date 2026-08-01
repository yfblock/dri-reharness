#!/usr/bin/env python3
"""Apply a manifest-declared source safety policy.

The sanitizer has no knowledge of a device or register vocabulary.  A policy
may reject a token or rewrite matching source text before compilation.
"""
from __future__ import annotations

import re
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from experiment_manifest import SafetyPolicy, load_manifest, manifest_digest  # noqa: E402


class SafetyPolicyError(ValueError):
    """Raised when source violates a manifest safety policy."""


def sanitize_text(source: str, policy: SafetyPolicy) -> tuple[str, tuple[str, ...]]:
    """Return sanitized source and the policy tokens observed in it."""
    observed = tuple(token for token in policy.forbidden_tokens if token in source)
    if not observed or policy.action == "allow":
        return source, observed
    if policy.action == "reject":
        raise SafetyPolicyError(
            f"source violates safety policy ({policy.failure_class}): {', '.join(observed)}"
        )
    updated = source
    for rule in policy.rewrite_rules:
        updated = re.sub(rule["pattern"], rule["replacement"], updated, flags=re.MULTILINE)
    remaining = tuple(token for token in observed if token in updated)
    if remaining:
        raise SafetyPolicyError(
            f"rewrite did not remove forbidden token(s) ({policy.failure_class}): {', '.join(remaining)}"
        )
    return updated, observed


def sanitize_source(path: str | Path, policy: SafetyPolicy,
                    *, receipt_path: str | Path | None = None) -> tuple[str, ...]:
    source_path = Path(path)
    original = source_path.read_text(encoding="utf-8")
    updated, observed = sanitize_text(original, policy)
    if updated != original:
        source_path.write_text(updated, encoding="utf-8")
    if receipt_path is not None:
        receipt = {
            "schema": 1,
            "policy_digest": manifest_digest(policy.to_dict()),
            "source_before_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "source_after_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
            "matched_tokens": list(observed),
            "changed": updated != original,
            "rewrite_rule_count": len(policy.rewrite_rules),
        }
        destination = Path(receipt_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return observed


def main(argv: list[str]) -> int:
    if len(argv) not in {2, 3}:
        print(f"usage: {argv[0]} SOURCE [MANIFEST]", file=sys.stderr)
        return 2
    source = Path(argv[1])
    manifest_path = Path(argv[2]) if len(argv) == 3 else None
    policy = SafetyPolicy()
    if manifest_path is not None:
        policy = load_manifest(manifest_path, repo_root=ROOT).runtime.safety_policy
    try:
        observed = sanitize_source(source, policy)
    except (OSError, SafetyPolicyError, ValueError) as exc:
        print(f"[sanitize] {exc}", file=sys.stderr)
        return 1
    if observed:
        print(f"[sanitize] applied manifest safety policy to {len(observed)} token(s)", file=sys.stderr)
    else:
        print("[sanitize] no policy violations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
