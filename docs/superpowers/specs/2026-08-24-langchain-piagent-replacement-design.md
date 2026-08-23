# LangChain/LangGraph Pi Agent Replacement Design

## Goal

Replace Pi Agent as the default LLM integration for reharness while keeping
the existing evidence extraction, generation contract, compilation, runtime,
trace comparison, and bounded repair policy authoritative.

## Scope

The replacement covers both existing LLM entry points:

1. The structured experiment path used by `ExperimentRunner`.
2. The direct backend generator path used by `generate_via_llm`.

LangGraph remains the outer workflow orchestrator. The existing
`ExperimentRunner` remains the owner of experiment stage ordering and retry
limits. Pi remains available only as an explicit compatibility backend through
`REHARNESS_LLM_BACKEND=pi`.

## Architecture

```text
LangGraph workflow
  -> existing ExperimentRunner
     -> LangChainBridge
        -> LangChain ChatModel
           -> OpenAI-compatible endpoint
```

The bridge is dependency-injected at the model boundary. Production creates a
LangChain `ChatOpenAI` instance lazily from environment/configuration; tests
inject a small callable fake and never require network access. The bridge
returns the same candidate shape consumed by the existing runner:

```json
{
  "code": "...",
  "scenario": [],
  "diagnostics": {}
}
```

The request retains protocol version, manifest digest, evidence digest,
immutable evidence, candidate, structured failure feedback, and remaining
iteration budget. Repair requests require feedback and candidate context.

## Configuration

The default backend is `langchain`. The following environment variables are
supported:

- `REHARNESS_LLM_BACKEND`: `langchain` (default) or `pi`.
- `REHARNESS_LLM_MODEL`: provider model id, defaulting to the project model
  configuration when present.
- `REHARNESS_LLM_BASE_URL`: OpenAI-compatible base URL.
- `REHARNESS_LLM_API_KEY`: API key. `OPENAI_API_KEY` is accepted as a fallback.
- `REHARNESS_LLM_TIMEOUT`: request timeout in seconds.
- `REHARNESS_LLM_TEMPERATURE`: numeric temperature, default `0`.

Project model metadata in `.reharness/pi/models.json` remains readable for
model id and base URL discovery, but secrets are read from environment
variables. The existing Pi auth file is not imported into LangChain.

## Output Handling

LangChain responses are normalized from common `AIMessage`, string, and
mapping forms. The parser accepts a fenced C/Rust block or a complete source
response, extracts an optional fenced JSON `scenario` array, and rejects an
empty or non-source response. Diagnostics retain model text and response
metadata for experiment artifacts without changing acceptance policy.

The parser is shared by structured and direct generation paths so Rust output
is not accidentally forced through the old C-only extractor.

## Failure Policy

Provider, timeout, malformed-output, and model-configuration failures surface
as adapter failures. They cannot accept a candidate. Compile, runtime, and
trace failures continue through the existing structured repair feedback and
iteration budgets. Every repaired candidate is rechecked by the generation
contract before proceeding.

No LangChain tool is allowed to write source files, modify manifests, or bypass
the existing safety and verification gates. The model receives evidence and
feedback only.

## Testing

- Unit tests cover configuration precedence, request construction, repair
  validation, response normalization, C/Rust extraction, scenario parsing, and
  provider failures using an injected fake model.
- Adapter tests verify the default backend is LangChain and the explicit Pi
  compatibility switch still constructs the existing subprocess bridge.
- Generator tests verify direct `generate_via_llm` uses LangChain by default
  and preserves backend-specific code extraction.
- Existing ExperimentRunner and LangGraph tests remain authoritative for the
  compile/runtime/trace/repair state machine.

