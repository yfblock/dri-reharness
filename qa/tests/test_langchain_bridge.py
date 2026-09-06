from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from langchain_bridge import (  # noqa: E402
    LangChainBridge,
    LangChainBridgeError,
    LangChainSettings,
    build_llm_bridge,
    extract_generated_code,
    load_langchain_settings,
    parse_model_response,
)


class Manifest:
    digest = "a" * 64


class LinuxManifest(Manifest):
    compile = SimpleNamespace(backend="linux", language="c", context="kbuild")
    runtime = SimpleNamespace(
        adapter="qemu",
        pci_identity=SimpleNamespace(vendor="0x1234", device="0x11e8"),
    )


class SafetyLinuxManifest(LinuxManifest):
    runtime = SimpleNamespace(
        adapter="qemu",
        pci_identity=SimpleNamespace(vendor="0x1234", device="0x11e8"),
        safety_policy=SimpleNamespace(
            forbidden_tokens=("IO_DMA_CMD",),
            action="rewrite",
            failure_class="safety",
        ),
    )


class GpioLinuxManifest(Manifest):
    compile = SimpleNamespace(backend="linux", language="c", context="kbuild")
    runtime = SimpleNamespace(
        adapter="qemu-platform",
        pci_identity=None,
        qemu=SimpleNamespace(bus="platform"),
    )


class FakeModel:
    def __init__(self, content: str):
        self.content = content
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.content, response_metadata={"model": "fake"})


def test_synthesize_uses_tool_call_form_when_available():
    """模型走 bind_tools 时, emit_driver_code 工具参数直接成为候选文件。"""
    from langchain_core.messages import AIMessage
    from langchain_bridge import LangChainBridge

    class ToolModel:
        def __init__(self):
            self.prompts = []

        def bind_tools(self, tools):
            outer = self
            class _Bound:
                def invoke(self, prompt):
                    outer.prompts.append(prompt)
                    return AIMessage(content="", tool_calls=[{
                        "name": "emit_driver_code",
                        "args": {"files": [
                            {"path": "demo.c", "code": "int probe(void) { return 0; }"},
                        ]},
                        "id": "call-1",
                    }])
            return _Bound()

    model = ToolModel()
    bridge = LangChainBridge(model=model)
    response = bridge.synthesize(LinuxManifest(), {"driver": "demo"})

    assert "int probe(void)" in response["code"]
    files = response.get("files") or []
    assert any(item.get("path") == "demo.c" for item in files)
    assert model.prompts, "tool 路径应收到同一份合成提示词"


def test_synthesize_falls_back_to_text_when_no_tool_calls():
    """模型不支持 bind_tools 或未调用工具时, 回退纯文本 fenced-code 解析。"""
    from langchain_bridge import LangChainBridge

    model = FakeModel("```c\nint fallback(void) { return 1; }\n```")
    bridge = LangChainBridge(model=model)
    response = bridge.synthesize(LinuxManifest(), {"driver": "demo"})
    assert "int fallback(void)" in response["code"]


def test_settings_environment_overrides_project_metadata(tmp_path, monkeypatch):
    """环境变量优先于项目级 config.toml 配置。"""
    (tmp_path / "config.toml").write_text(
        "[llm]\nmodel = \"project-model\"\n"
        "base_url = \"https://project.example/v1\"\n"
        "timeout = 90\ntemperature = 0.5\n", encoding="utf-8")

    for name in ("REHARNESS_LLM_MODEL", "REHARNESS_LLM_BASE_URL",
                 "REHARNESS_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    from langchain_bridge import load_langchain_settings
    project = load_langchain_settings(repo_root=tmp_path)
    assert project.model == "project-model"
    assert project.base_url == "https://project.example/v1"

    assert project.timeout == 90
    assert project.temperature == 0.5
    monkeypatch.setenv("REHARNESS_LLM_MODEL", "env-model")
    monkeypatch.setenv("REHARNESS_LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("REHARNESS_LLM_API_KEY", "env-key")
    overridden = load_langchain_settings(repo_root=tmp_path)
    assert overridden.model == "env-model"
    assert overridden.base_url == "https://env.example/v1"
    assert overridden.api_key == "env-key"


def test_settings_loads_project_api_key_from_config_toml(tmp_path, monkeypatch):
    """项目级 config.toml 直接提供 api_key 与数值参数。"""
    (tmp_path / "config.toml").write_text(
        "[llm]\nmodel = \"auth-model\"\n"
        "base_url = \"https://auth.example/v1\"\n"
        "api_key = \"project-key\"\n", encoding="utf-8")

    for name in ("REHARNESS_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    from langchain_bridge import load_langchain_settings
    settings = load_langchain_settings(repo_root=tmp_path)
    assert settings.model == "auth-model"
    assert settings.api_key == "project-key"
    assert settings.base_url == "https://auth.example/v1"


def test_extract_generated_code_accepts_c_rust_and_complete_source():
    assert extract_generated_code("```c\nint main(void) { return 0; }\n```") == \
        "int main(void) { return 0; }"
    assert extract_generated_code("```rust\nfn main() {}\n```") == "fn main() {}"
    assert extract_generated_code("#include <stdint.h>\nstatic int value;") == \
        "#include <stdint.h>\nstatic int value;"


def test_extract_generated_code_rejects_empty_or_non_source_text():
    with pytest.raises(LangChainBridgeError, match="valid source"):
        extract_generated_code("I cannot generate this driver")
    with pytest.raises(LangChainBridgeError, match="valid source"):
        extract_generated_code("   ")


def test_parse_model_response_extracts_scenario_and_diagnostics():
    response = SimpleNamespace(
        content=(
            "```c\nint main(void) { return 0; }\n```\n"
            "```json\n{\"scenario\":[{\"action\":\"probe\"}]}\n```"
        ),
        response_metadata={"model": "fake"},
    )

    parsed = parse_model_response(response)

    assert parsed["code"] == "int main(void) { return 0; }"
    assert parsed["scenario"] == [{"action": "probe"}]
    assert parsed["diagnostics"]["model"] == "fake"
    assert parsed["diagnostics"]["raw_output"].startswith("```c")


def test_parse_model_response_accepts_structured_mapping():
    parsed = parse_model_response({
        "code": "int main(void) { return 0; }",
        "scenario": [{"action": "probe"}],
        "response_metadata": {"model": "fake"},
    })

    assert parsed["code"].startswith("int main")
    assert parsed["scenario"] == [{"action": "probe"}]


def test_parse_model_response_accepts_structured_multifile_candidate():
    parsed = parse_model_response({
        "files": [
            {"path": "driver.c", "code": "int driver(void) { return 0; }"},
            {"path": "driver.h", "code": "int driver(void);"},
        ],
        "scenario": [{"action": "probe"}],
        "response_metadata": {"model": "fake"},
    })

    assert parsed["code"] == "int driver(void) { return 0; }"
    assert parsed["files"] == [
        {"path": "driver.c", "code": "int driver(void) { return 0; }"},
        {"path": "driver.h", "code": "int driver(void);"},
    ]
    assert parsed["scenario"] == [{"action": "probe"}]


def test_bridge_sends_synthesize_and_repair_envelopes():
    model = FakeModel("```c\nint main(void) { return 0; }\n```")
    bridge = LangChainBridge(model=model)
    evidence = {"facts": []}

    generated = bridge.synthesize(Manifest(), evidence)
    repaired = bridge.synthesize(
        Manifest(), evidence,
        feedback={"failure_class": "compile", "message": "bad", "details": {}},
        candidate={"code": "old"},
    )

    def envelope(prompt: str) -> dict:
        body = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
        return json.loads(body)

    first = envelope(model.prompts[0])
    second = envelope(model.prompts[1])
    assert generated["code"].startswith("int main")
    assert first["operation"] == "synthesize"
    assert first["manifest_digest"] == Manifest.digest
    assert first["evidence"] == evidence
    assert second["operation"] == "repair"
    assert second["candidate"] == {"code": "old"}
    assert second["feedback"]["failure_class"] == "compile"
    assert repaired["code"].startswith("int main")


def test_repair_prompt_puts_compact_requirements_after_large_envelope():
    model = FakeModel("```c\nint main(void) { return 0; }\n```")
    bridge = LangChainBridge(model=model)
    feedback = {
        "failure_class": "contract",
        "stage": "contract",
        "message": "registration route missing",
        "details": {
            "repair_requirements": {
                "missing_callback_routes": [
                    {"callback": "pci_driver.probe", "target": "edu_probe"}
                ],
                "preserve_register_operation_ids": ["op_11"],
            },
            "large_diagnostic": "x" * 10000,
        },
    }

    bridge.repair(LinuxManifest(), {"facts": []}, {"code": "old"}, feedback)

    prompt = model.prompts[0]
    directive = prompt.index("REPAIR DIRECTIVE")
    envelope = prompt.index("REQUEST ENVELOPE")
    assert directive > envelope
    assert directive > prompt.index("BACKEND-SPECIFIC GENERATION RULES")
    assert "missing_callback_routes" in prompt[directive:]
    assert "pci_driver.probe" in prompt[directive:]
    assert "preserve_register_operation_ids" in prompt[directive:]
    assert "x" * 10000 not in prompt[directive:]


def test_bridge_inlines_evidence_bundle_for_remote_model(tmp_path: Path):
    (tmp_path / "demo.formal.json").write_text(
        json.dumps({"driver": "demo", "modules": []}), encoding="utf-8")
    (tmp_path / "generation-contract.json").write_text(
        json.dumps({"register_operations": [{
            "op_id": "op_5", "module": "read_module",
            "kind": "Read", "digest": "0123456789abcdef",
        }]}), encoding="utf-8")
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    LangChainBridge(model=model).synthesize(
        LinuxManifest(), {"directory": str(tmp_path)})

    prompt = model.prompts[0]
    assert "generation_contract" in prompt
    assert "op_5" in prompt
    assert "0123456789abcdef" in prompt
    assert "operation_ownership" in prompt
    assert "read_module" in prompt


def test_bridge_inlines_backend_lowering_owner_plan_for_linux(tmp_path: Path):
    (tmp_path / "demo.formal.json").write_text(json.dumps({
        "driver": "demo",
        "modules": [{
            "name": "read_module",
            "ops": [{"Read": {
                "op_id": "op_5",
                "width": "B4",
                "addr": {"Fixed": {"base": "base", "offset": 0}},
                "var": "value",
            }}],
        }],
    }), encoding="utf-8")
    (tmp_path / "generation-contract.json").write_text(json.dumps({
        "register_operations": [{
            "op_id": "op_5", "module": "read_module", "kind": "Read",
        }],
    }), encoding="utf-8")
    (tmp_path / "demo.device-spec.json").write_text(json.dumps({
        "name": "demo",
        "functions": [{
            "name": "read_module",
            "ris_ref": "read_module",
            "role": "read_config",
            "is_callback_entry": True,
            "callback_table": "file_operations.read",
        }],
    }), encoding="utf-8")
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    LangChainBridge(model=model).synthesize(
        LinuxManifest(), {"directory": str(tmp_path)})

    prompt = model.prompts[0]
    assert "backend_lowering_plan" in prompt
    assert "verifier-owned" in prompt
    assert "owner_function" in prompt
    assert '"owner_function": "read_module"' in prompt
    assert '"callback": "file_operations.read"' in prompt


def test_qa_deterministic_model_replays_synthesis_and_repair():
    from deterministic_llm import DeterministicModel

    model = DeterministicModel([
        "```c\nint first(void) { return 0; }\n```",
        "```c\nint repaired(void) { return 0; }\n```",
    ])
    bridge = LangChainBridge(model=model)

    first = bridge.invoke_text("synthesis request")
    second = bridge.invoke_text("repair request")

    assert first == "```c\nint first(void) { return 0; }\n```"
    assert second == "```c\nint repaired(void) { return 0; }\n```"
    assert model.prompts == ["synthesis request", "repair request"]
    assert model.invocations == 2


def test_linux_structured_synthesis_includes_backend_lifecycle_guidance():
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    LangChainBridge(model=model).synthesize(
        LinuxManifest(), {"driver": "edu", "modules": []})

    prompt = model.prompts[0]
    assert "pci_driver" in prompt
    assert "misc_register" in prompt
    assert "module_pci_driver" in prompt


def test_linux_guidance_requires_exact_transaction_lowering_receipts():
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    LangChainBridge(model=model).synthesize(
        GpioLinuxManifest(), {
            "driver": "spi-client",
            "bus_type": "spi",
            "modules": [{
                "name": "fixture_spi_probe",
                "ops": [{
                    "kind": "tx_read",
                    "op_id": "op_2",
                    "transport": "spi",
                    "protocol": "spi_sync",
                    "target": "spi",
                    "selector": "&message",
                    "message": "&message",
                    "digest": "f" * 16,
                }],
            }],
        })

    prompt = model.prompts[0]
    assert "REHARNESS_TRANSACTION_OP" in prompt
    assert "status=lowered" in prompt
    assert "transport=<transport>" in prompt
    assert "digest=<digest>" in prompt


def test_synthesis_prompt_carries_manifest_safety_policy():
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    LangChainBridge(model=model).synthesize(
        SafetyLinuxManifest(), {"driver": "edu", "modules": []})

    prompt = model.prompts[0]
    assert "safety_policy" in prompt
    assert "IO_DMA_CMD" in prompt
    assert "must not emit" in prompt.lower()


def test_linux_gpio_guidance_requires_typed_callback_wiring():
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    LangChainBridge(model=model).synthesize(
        GpioLinuxManifest(), {
            "driver": "generic-gpio",
            "device_class": "gpio_controller",
            "bind": {"callbacks": {
                "gpio_chip.get": "gpio_get",
                "gpio_irq_chip.parent_handler": "gpio_parent_handler",
            }},
            "framework": {"callback_signatures": {
                "gpio_chip.get": {
                    "type": "int (*)(struct gpio_chip *, unsigned int)",
                    "return_type": "int",
                    "params": [{"type": "struct gpio_chip *"},
                               {"type": "unsigned int"}],
                    "variadic": False,
                },
            }},
        })

    prompt = model.prompts[0]
    assert "SUBSYSTEM CALLBACK WIRING" in prompt
    assert "gpio_chip" in prompt
    assert "parent_handler" in prompt
    assert "framework.callback_signatures" in prompt
    assert "struct gpio_chip *" in prompt
    assert "Do not call callback functions directly from probe" in prompt
    assert "irq_to_desc" in prompt
    assert "including operations in the probe" in prompt
    assert "state_read" in prompt
    assert "global owner" in prompt.lower()
    assert "call it without a receipt" in prompt.lower()
    assert "gpio_irq_chip_set_chip" in prompt
    assert "girq->parents" in prompt
    assert "girq->num_parents" in prompt
    assert "platform_get_irq" in prompt


def test_bridge_repair_requires_feedback():
    bridge = LangChainBridge(model=FakeModel("```c\nint main(void) { return 0; }\n```"))
    with pytest.raises(ValueError, match="requires feedback"):
        bridge.repair(Manifest(), {"facts": []}, {"code": "old"}, None)


def test_bridge_wraps_model_and_output_failures():
    class FailingModel:
        def invoke(self, prompt):
            raise RuntimeError("provider unavailable")

    with pytest.raises(LangChainBridgeError, match="model invocation failed"):
        LangChainBridge(model=FailingModel()).synthesize(Manifest(), {"facts": []})

    with pytest.raises(LangChainBridgeError, match="valid source"):
        LangChainBridge(model=FakeModel("not source prose")).synthesize(
            Manifest(), {"facts": []})


def test_provider_model_disables_implicit_retries(monkeypatch):
    created = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setitem(
        sys.modules, "langchain_openai",
        SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )
    bridge = LangChainBridge(settings=LangChainSettings(
        model="model", timeout=7, temperature=0.0))

    bridge._model_instance()

    assert created["timeout"] == 7
    assert created["max_retries"] == 0




def test_settings_default_to_gpt_56_luna_without_project_metadata(tmp_path, monkeypatch):
    for name in ("REHARNESS_LLM_MODEL", "REHARNESS_LLM_BASE_URL",
                 "REHARNESS_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    settings = load_langchain_settings(repo_root=tmp_path)

    assert settings.model == "gpt-5.6-luna"


def test_build_llm_bridge_defaults_to_langchain(tmp_path, monkeypatch):

    bridge = build_llm_bridge(tmp_path)

    assert isinstance(bridge, LangChainBridge)




def test_direct_generator_uses_langchain_for_c_and_rust(monkeypatch):
    import backends.llm_bridge as generator_bridge
    import langchain_bridge as langchain_module

    formal = {"driver": "demo", "register_map": [], "modules": []}

    class _device:
        name, cls = "demo", "device"
        functions: list = []
        state: list = []
        registers: list = []
        buses: list = []
        irqs: list = []
        clocks: list = []
        resources: list = []
        dma: list = []
        includes: list = []
        constants: dict = {}

        def __getattr__(self, attr):
            return lambda *a, **k: None

    class _bind:
        primitives, types, state, callbacks, includes = [], [], [], [], []

        def __getattr__(self, attr):
            return lambda *a, **k: None

    device, bind = _device(), _bind()
    calls: list[str] = []

    def fake_call(prompt, *, timeout=120, **kwargs):
        calls.append(prompt)
        return "```rust\nfn main() {}\n```" if "Rust" in prompt else \
            "```c\nint main(void) { return 0; }\n```"

    monkeypatch.setattr(langchain_module, "call_langchain", fake_call)

    c_code = generator_bridge.generate_via_llm(
        formal, device, bind, backend="harness")
    rust_code = generator_bridge.generate_via_llm(
        formal, device, bind, backend="rust_baremetal")

    assert "int main(void)" in c_code
    assert "fn main()" in rust_code
    assert len(calls) == 2


def test_direct_generator_preserves_multifile_candidate_envelope(monkeypatch):
    import backends.llm_bridge as generator_bridge
    import langchain_bridge as langchain_module

    formal = {"driver": "demo", "register_map": [], "modules": []}

    class _device:
        name, cls = "demo", "device"
        functions: list = []
        state: list = []
        registers: list = []
        buses: list = []
        irqs: list = []
        clocks: list = []
        resources: list = []
        dma: list = []
        includes: list = []
        constants: dict = {}

        def __getattr__(self, attr):
            return lambda *a, **k: None

    class _bind:
        primitives, types, state, callbacks, includes = [], [], [], [], []

        def __getattr__(self, attr):
            return lambda *a, **k: None

    device, bind = _device(), _bind()
    response = (
        "```json\n"
        '{"files": [{"path": "demo.c", "code": '
        '"int main(void) { return 0; }"}, '
        '{"path": "demo.h", "code": "int main(void);"}]}\n'
        "```"
    )

    monkeypatch.setattr(langchain_module, "call_langchain", lambda *args, **kwargs: response)

    generated = generator_bridge.generate_via_llm(
        formal, device, bind, backend="harness")

    assert "int main(void)" in generated
    assert generated.files == [
        {"path": "demo.c", "code": "int main(void) { return 0; }"},
        {"path": "demo.h", "code": "int main(void);"},
    ]


def test_direct_generator_materializes_primary_source_and_auxiliary_files():
    from backends.llm_bridge import GeneratedCode, generated_file_entries

    generated = GeneratedCode(
        "/* generated */\nint main(void) { return 0; }",
        files=[
            {"path": "demo.c", "code": "int main(void) { return 0; }"},
            {"path": "include/demo.h", "code": "int main(void);"},
        ],
    )

    assert generated_file_entries(generated, default_path="harness.c") == [
        {"path": "demo.c", "code": "/* generated */\nint main(void) { return 0; }"},
        {"path": "include/demo.h", "code": "int main(void);"},
    ]


def test_direct_generator_accepts_an_injected_model():
    import backends.harness as harness

    formal = {"driver": "demo", "register_map": [], "modules": []}

    class _device:
        name, cls = "demo", "device"
        functions: list = []
        state: list = []
        registers: list = []
        buses: list = []
        irqs: list = []
        clocks: list = []
        resources: list = []
        dma: list = []
        includes: list = []
        constants: dict = {}

        def __getattr__(self, attr):
            return lambda *a, **k: None

    class _bind:
        primitives, types, state, callbacks, includes = [], [], [], [], []

        def __getattr__(self, attr):
            return lambda *a, **k: None

    device, bind = _device(), _bind()
    model = FakeModel("```c\nint main(void) { return 0; }\n```")

    code = harness.generate(formal, device, bind, model=model)

    assert "int main(void)" in code
    assert len(model.prompts) == 1



def test_generator_evidence_includes_receipt_digests_for_register_ops():
    from backends.llm_bridge import build_evidence_json, _modules_ris_text
    from backends.common import ris_op_digest

    op = {
        "Read": {
            "op_id": "op_1",
            "width": "B4",
            "addr": {"Fixed": {"base": "base", "offset": 4}},
            "var": "value",
            "access_domain": "mmio",
            "evidence": {},
        }
    }
    formal = {"driver": "demo", "register_map": [],
              "modules": [{"name": "demo_probe", "ops": [op]}]}
    device = SimpleNamespace(name="demo", cls="generic_mmio")
    bind = SimpleNamespace(primitives=[], types=[], state=[], callbacks=[], includes=[])

    evidence = json.loads(build_evidence_json(formal, device, bind))
    assert evidence["modules"] == ["demo_probe"]

    ris_text = _modules_ris_text(formal)
    assert "@op_1" in ris_text
    assert "digest=%s" % ris_op_digest(op) in ris_text
    # the op dict itself must stay unannotated (oracle digests would shift)
    assert "_receipt_digest" not in json.dumps(op)


def test_generator_evidence_preserves_dynamic_fixed_address_expression():
    from backends.llm_bridge import _modules_ris_text

    op = {
        "Read": {
            "op_id": "op_dynamic",
            "width": "B4",
            "addr": {"Fixed": {
                "base": "priv->mmio + *off",
                "offset": 0,
            }},
            "var": "value",
        }
    }
    formal = {"driver": "demo", "register_map": [],
              "modules": [{"name": "demo_probe", "ops": [op]}]}

    assert "priv->mmio + *off" in _modules_ris_text(formal)


def test_generator_evidence_preserves_proven_loop_shape():
    from backends.llm_bridge import _modules_ris_text

    formal = {
        "driver": "demo",
        "register_map": [],
        "modules": [{"name": "demo_irq", "ops": [{"Loop": {
            "loop_kind": "while",
            "guard": {"Var": "ready() && retry-- >= 0"},
            "count": {"Var": "retry"},
            "relation": "post-decrement",
            "body": [],
            "bounded": True,
        }}]}],
    }

    ris_text = _modules_ris_text(formal)
    assert "LOOP while" in ris_text
    assert "relation=post-decrement" in ris_text
    assert "count=retry" in ris_text
    assert "bounded" in ris_text


def test_generator_evidence_includes_framework_signatures_and_resources():
    from backends.llm_bridge import build_evidence_json
    from extractor.spec import ResourceFact

    function = SimpleNamespace(
        name="gpio_parent_handler",
        role="interrupt_handler",
        context="irq",
        source="driver.c:10",
        ris_ref="gpio_parent_handler",
        is_callback_entry=True,
        callback_table="gpio_irq_chip.parent_handler",
        signature=SimpleNamespace(
            params=[SimpleNamespace(name="desc", type="LogicalIRQ", from_expr=None)],
            return_type="Void",
        ),
    )
    facts = SimpleNamespace(
        constants={}, structs=[],
        resources=[ResourceFact(
            name="irq0", acquisition="platform_get_irq", binds_to=None)],
        callbacks={"gpio_irq_chip.parent_handler": "gpio_parent_handler"},
        callback_signatures={
            "gpio_irq_chip.parent_handler": {
                "type": "void (*)(struct irq_desc *)",
                "return_type": "void",
                "params": [{"type": "struct irq_desc *"}],
                "variadic": False,
            },
        },
        error_paths=["return -ENOMEM"],
        helper_calls=["devm_gpiochip_add_data"],
        source_snippets={},
    )
    device = SimpleNamespace(
        name="generic-gpio", cls="gpio_controller", functions=[function])
    bind = SimpleNamespace(
        primitives=[], types=[], state=[], callbacks=[], includes=[])

    evidence = json.loads(build_evidence_json(
        {"driver": "generic-gpio", "register_map": [], "modules": []},
        device, bind, facts))

    assert evidence["functions"][0]["signature"]["params"][0]["name"] == "desc"
    assert evidence["functions"][0]["callback_table"] == "gpio_irq_chip.parent_handler"
    assert evidence["resources"] == [{
        "name": "irq0", "type": None,
        "acquisition": "platform_get_irq", "binds_to": None,
    }]
    assert evidence["framework"]["helper_calls"] == ["devm_gpiochip_add_data"]
    assert evidence["framework"]["error_paths"] == ["return -ENOMEM"]
    assert evidence["framework"]["callback_signatures"][
        "gpio_irq_chip.parent_handler"]["params"] == [
            {"type": "struct irq_desc *"}]


def test_lowering_contract_normalizes_model_receipt_kind_case():
    from gate.backend_lowering_oracle import verify_backend_lowering

    op = {
        "Read": {
            "op_id": "op_1",
            "width": "B4",
            "addr": {"Fixed": {"base": "base", "offset": 4}},
            "var": "value",
            "access_domain": "mmio",
            "evidence": {},
        }
    }
    formal = {"driver": "demo", "modules": [{"name": "probe", "ops": [op]}]}
    from backends.common import ris_op_digest
    digest = ris_op_digest(op)

    report = verify_backend_lowering(
        formal,
        f"/* REHARNESS_RIS_OP id=op_1 kind=read status=lowered digest={digest} */\n"
        "value = readl(base + 4);\n",
    )

    assert report["complete"] is True, report


def test_module_cli_forwards_stdin_to_langchain(monkeypatch):
    import langchain_bridge as module

    calls: list[tuple[str, int]] = []

    def fake_call(prompt, *, timeout=120, **kwargs):
        calls.append((prompt, timeout))
        return "```c\nint main(void) { return 0; }\n```"

    monkeypatch.setattr(module, "call_langchain", fake_call)
    output = StringIO()

    assert module.main(["--timeout", "17"],
                       input_stream=StringIO("prompt"),
                       output_stream=output) == 0
    assert calls == [("prompt", 17)]
    assert output.getvalue().startswith("```c")


def test_direct_generator_feeds_ris_text_and_chunks_by_ris_size():
    """Module ops reach the prompt as text RIS (with receipt digests), not
    JSON; oversized drivers chunk on rendered RIS size."""
    import backends.llm_bridge as generator_bridge

    ops = [{"Write": {"op_id": "op_%d" % i, "width": "B4",
                      "addr": {"Symbolic": {"device": "mmio_x",
                                            "register": "REG_%d" % i}},
                      "value": {"Const": i}, "intent": "Config",
                      "reliability": "Exact",
                      "evidence": {"source": "drv.c", "line": i}}}
           for i in range(400)]
    formal = {"driver": "big", "register_map": [], "modules": [
        {"name": "mod_a", "ops": ops[:300]},
        {"name": "mod_b", "ops": ops[300:]}]}

    def fn(name):
        return SimpleNamespace(
            name=name, role="init", context="probe", source="drv.c:1",
            ris_ref=name, is_callback_entry=False, callback_table=None,
            signature=SimpleNamespace(params=[], return_type="Void"))

    device = SimpleNamespace(name="big", cls="generic_mmio",
                             functions=[fn("mod_a"), fn("mod_b")])
    bind = SimpleNamespace(primitives=[], types=[], state=[],
                           callbacks=[], includes=[])

    prompts = []

    def fake_call(prompt, *, timeout=120, **kwargs):
        prompts.append(prompt)
        assert "__EVIDENCE__" not in prompt
        assert "__RIS__" not in prompt
        if "SCAFFOLD PART" in prompt:
            assert "(none for this part" in prompt
            return "```c\nint scaffold(void);\n```"
        if " of 3." in prompt:
            assert "EXISTING SCAFFOLD" in prompt
            assert "module mod_" in prompt
            assert "digest=" in prompt
            assert prompt.index("```json") < prompt.index("module mod_")
            return "```c\nvoid part_fn(void) {}\n```"
        return "```c\nint single(void) { return 0; }\n```"

    monkeypatch_local = None
    import langchain_bridge as langchain_module
    saved = langchain_module.call_langchain
    langchain_module.call_langchain = fake_call
    try:
        generator_bridge.call_llm = fake_call
        gen = generator_bridge.generate_via_llm(
            formal, device, bind, backend="harness")
    finally:
        langchain_module.call_langchain = saved

    assert len(prompts) == 3  # scaffold + 2 parts
    assert [f["path"] for f in gen.files] == [
        "harness.c", "part-00-scaffold.c", "part-01.c", "part-02.c"]
    assert "module mod_a {" in prompts[1]
    assert "module mod_b {" in prompts[2]
    assert "digest=" in prompts[1]
