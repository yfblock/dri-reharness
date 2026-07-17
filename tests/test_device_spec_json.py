from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


REHARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REHARNESS))

from extractor.spec import (Binding, DeviceSpec, Effect, FunctionSpec, Param,
                            RegisterDesc, Resource, Signature, StateField,
                            device_spec_from_dict, device_spec_to_dict)


def _spec() -> DeviceSpec:
    return DeviceSpec(
        name="json-device",
        cls="gpio_controller",
        source="drivers/gpio/json-device.c",
        state=[
            StateField("base", "MmioBase", "priv->base"),
            StateField("shadow", "UIntArray"),
        ],
        resources=[
            Resource("mmio0", "MmioResource", True, "base"),
            Resource("irq0", "IrqResource", False),
        ],
        registers=[
            RegisterDesc("DATA", "B4", 0x10),
            RegisterDesc("ALT", "B2", 0x24, "aux"),
        ],
        invariants=["line < 32", "base is mapped"],
        functions=[FunctionSpec(
            name="json_probe",
            signature=Signature(
                params=[
                    Param("pdev", "DeviceState", "platform_device"),
                    Param("flags", "UInt"),
                ],
                return_type="UInt",
            ),
            role="probe",
            context="boot",
            source="json-device.c:42",
            binds=[
                Binding("dev", "DeviceState", "pdev"),
                Binding("base", "MmioBase", "priv->base"),
            ],
            requires=["resources_available"],
            ensures=["device_state == READY"],
            effects=[
                Effect("reg", "writes_register(DATA)", {
                    "register": "DATA",
                    "path": ["probe", {"branch": 1}],
                    "exact": True,
                    "ratio": 0.5,
                    "optional": None,
                }),
                Effect("state", "sets_shadow", {"indices": [0, 1]}),
            ],
            ris_ref="json_probe",
            is_callback_entry=True,
            callback_table="platform_driver.probe",
        )],
    )


def _raises(function, expected: str) -> None:
    try:
        function()
    except (TypeError, ValueError) as error:
        assert expected in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {expected!r}")


def test_device_spec_json_roundtrip_is_complete_and_json_serializable():
    original = _spec()
    document = device_spec_to_dict(original)
    assert document["schema"] == 1
    assert document["class"] == "gpio_controller"
    function = document["functions"][0]
    assert function["signature"]["params"][0]["from_expr"] == \
        "platform_device"
    assert function["binds"][1]["from_expr"] == "priv->base"
    assert function["effects"][0]["detail"]["path"][1] == {"branch": 1}
    assert function["is_callback_entry"] is True
    assert function["callback_table"] == "platform_driver.probe"

    encoded = json.dumps(document, sort_keys=True)
    restored = device_spec_from_dict(json.loads(encoded))
    assert restored == original
    assert device_spec_to_dict(restored) == document


def test_device_spec_json_roundtrip_has_no_mutable_aliases():
    original = _spec()
    document = device_spec_to_dict(original)
    restored = device_spec_from_dict(document)

    document["state"][0]["name"] = "mutated_document"
    document["functions"][0]["effects"][0]["detail"]["path"][1][
        "branch"] = 99
    assert original.state[0].name == "base"
    assert restored.state[0].name == "base"
    assert restored.functions[0].effects[0].detail["path"][1]["branch"] == 1

    restored.state[1].name = "mutated_object"
    restored.functions[0].effects[1].detail["indices"].append(2)
    assert original.state[1].name == "shadow"
    assert original.functions[0].effects[1].detail["indices"] == [0, 1]


def test_device_spec_json_rejects_unknown_schema_and_missing_fields():
    document = device_spec_to_dict(_spec())

    unknown = copy.deepcopy(document)
    unknown["schema"] = 2
    _raises(lambda: device_spec_from_dict(unknown),
            "unsupported DeviceSpec schema")

    boolean_schema = copy.deepcopy(document)
    boolean_schema["schema"] = True
    _raises(lambda: device_spec_from_dict(boolean_schema),
            "unsupported DeviceSpec schema")

    for path, mutate, expected in (
        ("top", lambda item: item.pop("functions"), "missing required field"),
        ("function",
         lambda item: item["functions"][0].pop("ris_ref"),
         "missing required field"),
        ("signature",
         lambda item: item["functions"][0]["signature"].pop("params"),
         "missing required field"),
        ("effect",
         lambda item: item["functions"][0]["effects"][0].pop("detail"),
         "missing required field"),
    ):
        mutated = copy.deepcopy(document)
        mutate(mutated)
        _raises(lambda value=mutated: device_spec_from_dict(value), expected)


def test_device_spec_json_rejects_wrong_types_and_unknown_fields():
    document = device_spec_to_dict(_spec())
    mutations = []

    def case(change, expected):
        value = copy.deepcopy(document)
        change(value)
        mutations.append((value, expected))

    case(lambda item: item.update({"state": {}}),
         "device_spec.state must be an array")
    case(lambda item: item["resources"][0].update({"required": 1}),
         "required must be a boolean")
    case(lambda item: item["registers"][0].update({"offset": True}),
         "offset must be an integer")
    case(lambda item: item["registers"][0].update({"width": "B3"}),
         "unsupported value")
    case(lambda item: item["functions"][0].update({"role": "invented"}),
         "role has unsupported value")
    case(lambda item: item["functions"][0].update({
        "is_callback_entry": 1}), "is_callback_entry must be a boolean")
    case(lambda item: item["functions"][0].update({
        "is_callback_entry": False}),
        "callback_table requires is_callback_entry=true")
    case(lambda item: item["functions"][0]["effects"][0].update({
        "detail": []}), "detail must be an object")
    case(lambda item: item.update({"unexpected": 1}), "unknown field")
    case(lambda item: item["functions"][0].update({"unexpected": 1}),
         "unknown field")

    for mutated, expected in mutations:
        _raises(lambda value=mutated: device_spec_from_dict(value), expected)


def test_device_spec_to_dict_rejects_invalid_object_and_non_json_detail():
    _raises(lambda: device_spec_to_dict({}), "must be a DeviceSpec")

    invalid = _spec()
    invalid.functions[0].effects[0].detail["bad"] = {1, 2}
    _raises(lambda: device_spec_to_dict(invalid), "contains non-JSON value")

    invalid = _spec()
    invalid.functions[0].effects[0].detail["bad"] = float("nan")
    _raises(lambda: device_spec_to_dict(invalid), "finite JSON number")


def _run_standalone() -> int:
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception:
            failures += 1
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
