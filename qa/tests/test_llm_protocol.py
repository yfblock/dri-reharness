from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from llm_protocol import (SynthesisRequest, SynthesisResponse,
                              parse_synthesis_response, render_synthesis_prompt)


class Manifest:
    digest = "a" * 64


def test_request_round_trip_and_repair_requires_feedback():
    request = SynthesisRequest(
        "repair", Manifest.digest, "b" * 64, {"ris": [], "spec": {}},
        candidate={"code": "old"},
        feedback={"failure_class": "compile", "message": "bad", "details": {}},
        remaining_budget={"compile": 1},
    )
    assert SynthesisRequest.from_dict(json.loads(request.to_json())) == request
    with pytest.raises(ValueError, match="requires feedback"):
        SynthesisRequest("repair", Manifest.digest, "b" * 64, {})


def test_response_rejects_malformed_success_and_accepts_scenario():
    response = SynthesisResponse(True, code="int main(void) { return 0; }", scenario=[{"action": "probe"}])
    assert parse_synthesis_response(response.to_dict()).scenario == ({"action": "probe"},)
    with pytest.raises(ValueError, match="requires non-empty code"):
        SynthesisResponse(True)
    with pytest.raises(ValueError, match="scenario entries"):
        SynthesisResponse(True, code="valid", scenario=["not-an-object"])


def test_prompt_contains_only_envelope_data():
    request = SynthesisRequest("synthesize", Manifest.digest, "b" * 64, {"device": "opaque"})
    prompt = render_synthesis_prompt(request)
    assert "REQUEST ENVELOPE" in prompt
    assert json.dumps(request.to_dict(), indent=2, sort_keys=True) in prompt
    assert "gpio" not in prompt.lower()



def test_response_parser_rejects_non_json():
    with pytest.raises(ValueError, match="valid JSON"):
        parse_synthesis_response("model prose")
