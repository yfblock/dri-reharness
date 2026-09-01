# LangChain/LangGraph Pi Agent Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LangChain the default LLM implementation for both reharness generation entry points while preserving the existing LangGraph and ExperimentRunner verification contract.

**Architecture:** Add a lazy LangChain bridge with the existing `PiRequest` envelope as its input contract and a normalized candidate response as its output contract. Route the structured experiment adapter and direct backend generator through this bridge by default, with an explicit `REHARNESS_LLM_BACKEND=pi` compatibility path. Keep all acceptance and repair decisions in existing deterministic components.

**Tech Stack:** Python 3.12, LangChain Core, `langchain-openai`, LangGraph 1.x, Pydantic-compatible response parsing, pytest, existing Pi protocol types.

---

### Task 1: Add failing bridge and parser tests

**Files:**
- Create: `qa/tests/test_langchain_bridge.py`
- Modify: `qa/tests/_bootstrap.py` only if the new module cannot be imported through the existing `src` path setup

- [x] **Step 1: Write tests for source extraction and response normalization**

Add tests that require `extract_generated_code()` to accept ` ```c ` and
` ```rust ` blocks, accept a complete source response, reject empty prose, and
require a non-empty extracted source. Add a test that `parse_model_response()`
returns code, a JSON `scenario` array, and diagnostics from a fake response
object exposing `.content`.

- [x] **Step 2: Write tests for request construction and repair invariants**

Use a fake model with an `invoke(prompt)` method. Instantiate
`LangChainBridge(model=fake)` and assert that a synthesize call includes the
protocol envelope, manifest digest, evidence digest, and evidence. Assert that
a repair call includes the old candidate and feedback. Assert that constructing
or invoking repair without feedback raises the same validation error as
`PiRequest`.

- [x] **Step 3: Write tests for model failures and backend configuration**

Assert that an exception from the fake model is propagated as a bridge error,
that an invalid response is rejected, and that environment configuration takes
precedence over project model metadata. Do not make these tests require
`langchain_openai` or network access.

- [x] **Step 4: Run the new tests and verify the expected RED state**

Run:

```bash
PYTHONPATH=src:qa:qa/verification python3 -m pytest -q qa/tests/test_langchain_bridge.py
```

Expected result: collection or test failures because `langchain_bridge` and
its public parser/bridge functions do not yet exist.

### Task 2: Implement the lazy LangChain bridge

**Files:**
- Create: `src/langchain_bridge.py`
- Modify: `src/pi_bridge.py` only if a shared response helper is needed without changing the Pi wire protocol

- [x] **Step 1: Add settings and project metadata loading**

Define a frozen settings object with model, base URL, API key, timeout, and
temperature. Read `REHARNESS_LLM_MODEL`, `REHARNESS_LLM_BASE_URL`,
`REHARNESS_LLM_API_KEY`, `OPENAI_API_KEY`, `REHARNESS_LLM_TIMEOUT`, and
`REHARNESS_LLM_TEMPERATURE`. When model or base URL is unset, read the first
provider/model entry from `<repo>/.reharness/pi/models.json`; never read an API
secret from that file.

- [x] **Step 2: Add response parsing independent of LangChain imports**

Implement parsers for strings, mappings, and objects with `.content`. Extract
the first fenced C/Rust/source block, otherwise accept text containing clear C
or Rust source markers. Parse the first valid fenced JSON object containing a
`scenario` array of objects. Return JSON-compatible diagnostics and raise a
bridge-specific `LangChainBridgeError` for empty or non-source output.

- [x] **Step 3: Add lazy ChatOpenAI construction and bridge invocation**

Implement `LangChainBridge(model=None, settings=None, repo_root=None)`.
Injected models are used directly by tests. Without an injected model,
`langchain_openai.ChatOpenAI` is imported and constructed only on first use
with the configured model, base URL, API key, timeout, and temperature. The
bridge builds a validated `PiRequest`, calls `render_pi_prompt(request)`,
invokes the model, and returns `code`, `scenario`, and `diagnostics`.

- [x] **Step 4: Run bridge tests and verify GREEN**

Run the Task 1 pytest command. Expected result: all bridge/parser tests pass
without the LangChain provider package or network.

### Task 3: Route the structured experiment adapter through LangChain

**Files:**
- Modify: `qa/verification/runtime_adapters.py`
- Test: `qa/tests/test_langchain_bridge.py`
- Test: `qa/tests/test_runtime_adapters.py`

- [x] **Step 1: Add a failing backend-selection test**

Test `build_adapters()` with `REHARNESS_LLM_BACKEND` unset and assert that its
`pi` protocol object is a `LangChainBridge`. Test with `REHARNESS_LLM_BACKEND=pi`
and assert that the object is the existing `SubprocessPiBridge`. Test an
unknown value and assert a clear `RuntimeAdapterError` or `ValueError`.

- [x] **Step 2: Implement explicit backend selection**

Add a small factory in `runtime_adapters.py` or `langchain_bridge.py` that
returns the default `LangChainBridge`, returns `SubprocessPiBridge` only for
`pi`, and rejects all other values. Preserve the existing command path and
constructor timeout for the Pi compatibility branch. Leave the attribute name
`Adapters.pi` unchanged because `ExperimentRunner` consumes the protocol, not
the implementation name.

- [x] **Step 3: Run adapter and runner regression tests**

Run:

```bash
PYTHONPATH=src:qa:qa/verification python3 -m pytest -q \
  qa/tests/test_langchain_bridge.py \
  qa/tests/test_runtime_adapters.py \
  qa/tests/test_experiment_runner.py \
  qa/tests/test_pi_bridge_protocol.py
```

Expected result: the new selection tests and all existing protocol/runner
tests pass.

### Task 4: Route direct backend generation through LangChain

**Files:**
- Modify: `src/generator/llm_bridge.py`
- Test: `qa/tests/test_langchain_bridge.py`

- [x] **Step 1: Add a failing direct-generation routing test**

Monkeypatch the LangChain text invocation and call `generate_via_llm()` with a
minimal formal/device/bind fixture. Assert that the generated C backend uses
the returned C block and that a Rust backend uses the returned Rust block.
Assert that the default route does not call the Pi subprocess. Add an explicit
`REHARNESS_LLM_BACKEND=pi` test that keeps the legacy route available.

- [x] **Step 2: Implement backend-aware text invocation**

Keep prompt-template and evidence construction unchanged. Change `call_llm()`
to select LangChain by default and Pi only when explicitly configured. Pass
the requested timeout through. Use the shared response text normalization so
the Rust path accepts ` ```rust ` instead of the old C-only extractor. Preserve
the generated-file prefix and existing function signature.

- [x] **Step 3: Run direct generator tests and existing generator checks**

Run the focused bridge test file and the repository tests covering generator
imports/no-hardcoding. Expected result: both C and Rust direct generation use
the LangChain route under default configuration.

### Task 5: Add dependencies, runtime documentation, and LangGraph integration coverage

**Files:**
- Modify: `requirements-langgraph.txt`
- Modify: `README.md`
- Modify: `src/langgraph_workflow/tools.py` only if an explicit LLM backend option must be passed through workflow input
- Test: `qa/tests/test_langgraph_workflow.py`

- [x] **Step 1: Add the production dependency ranges**

Declare `langgraph`, `langchain-core`, and `langchain-openai` in
`requirements-langgraph.txt` with compatible major-version ranges. Keep the
imports lazy enough that analysis-only workflows still produce a useful
missing-dependency error before a model call.

- [x] **Step 2: Document configuration and selection**

Replace the stale `REHARNESS_LLM_CMD` description with the LangChain default,
the OpenAI-compatible endpoint variables, the API-key variables, and the
explicit Pi compatibility command. Document that LangGraph analysis-only mode
does not invoke a model and that experiment/generation acceptance still
requires contract, compile, runtime, and trace gates.

- [x] **Step 3: Add LangGraph integration assertions**

Add a test using an injected pipeline or adapter factory to prove that the
LangGraph workflow remains responsible for orchestration while the pipeline
receives the selected bridge. Keep tests offline and use fake models.

- [x] **Step 4: Run focused LangGraph tests**

Run:

```bash
PYTHONPATH=src:qa:qa/verification python3 -m pytest -q \
  qa/tests/test_langgraph_workflow.py \
  qa/tests/test_run_dispatcher.py
```

### Task 6: Verify the completed replacement

**Files:**
- Test: `qa/tests/test_langchain_bridge.py`
- Test: `qa/tests/test_runtime_adapters.py`
- Test: `qa/tests/test_experiment_runner.py`
- Test: `qa/tests/test_langgraph_workflow.py`
- Modify: none unless verification exposes a directly scoped defect

- [x] **Step 1: Run static and syntax checks**

Run:

```bash
python3 -m compileall -q src/langchain_bridge.py src/generator/llm_bridge.py qa/verification/runtime_adapters.py
git diff --check
```

- [x] **Step 2: Run all targeted regression tests**

Run the focused bridge, adapter, runner, Pi protocol, LangGraph, dispatcher,
and no-hardcoding tests together. Confirm that failures, if any, are not
caused by missing optional provider credentials in offline tests.

- [x] **Step 3: Run an analysis-only LangGraph smoke**

Run:

```bash
./run.sh langgraph edu.c --mode analysis --backend linux
```

Confirm it completes without making a model request and writes the evidence
bundle under `artifacts/langgraph/edu/`.

- [x] **Step 4: Audit the replacement boundary**

Search all production call sites for `pi_synth.sh`, `SubprocessPiBridge`, and
`call_llm`. Confirm Pi calls remain only behind the explicit `pi` compatibility
branch and that every default generation/experiment route resolves to
`LangChainBridge`.
