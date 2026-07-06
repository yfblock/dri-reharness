"""Generation readiness scoring (plan Milestone 8).

Reports whether a driver is suitable for RIS-only / function-skeleton /
bare-metal / Linux generation, with a numeric score and a blocker list.
"""
from __future__ import annotations
from .metrics import driver_metrics


def score(device_spec, formal: dict, warnings: list[str]) -> dict:
    met = driver_metrics(formal, n_clang_diag=len(warnings))
    total_ops = met["total_ops"] or 1
    addr_total = met["symbolic"] + met["fixed"] + met["computed"] or 1

    ris_quality = round(
        0.7 * (met["symbolic"] / addr_total)
        + 0.2 * ((total_ops - met["unknown_value"]) / total_ops)
        + 0.1 * (1.0 if met["computed"] == 0 else 0.5),
        3,
    )

    fns = device_spec.functions
    with_role = sum(1 for f in fns if f.role and f.role not in ("unknown", "helper"))
    function_spec_quality = round(with_role / len(fns), 3) if fns else 0.0

    regs_mapped = len(formal.get("register_map", []))
    resources_resolved = sum(1 for r in device_spec.resources if r.bind or r.type.endswith("Resource"))
    device_spec_quality = round(
        0.5 * (min(regs_mapped, 8) / 8)
        + 0.3 * (resources_resolved / max(len(device_spec.resources), 1))
        + 0.2 * (1.0 if device_spec.state else 0.0),
        3,
    )

    blockers: list[str] = []
    if met["computed"] > 0:
        blockers.append(f"{met['computed']} dynamic (computed) register address(es)")
    if met["unknown_value"] > 0:
        blockers.append(f"{met['unknown_value']} unknown (Top) value(s)")
    unroled = [f.name for f in fns if f.role in ("unknown",)]
    if unroled:
        blockers.append(f"missing role for: {', '.join(unroled)}")

    callback_entries = [f for f in fns if f.is_callback_entry]
    unbound_callbacks = [f.name for f in callback_entries if not f.callback_table]
    if unbound_callbacks:
        blockers.append(f"callback entry without table binding: {', '.join(unbound_callbacks)}")

    baremetal_ready = (met["computed"] == 0 and ris_quality >= 0.7)
    linux_ready = (baremetal_ready and function_spec_quality >= 0.6
                   and not unbound_callbacks and len(device_spec.registers) > 0)

    return {
        "ris_quality": ris_quality,
        "function_spec_quality": function_spec_quality,
        "device_spec_quality": device_spec_quality,
        "backend_bare_metal_ready": baremetal_ready,
        "backend_linux_ready": linux_ready,
        "blockers": blockers,
    }


def format_score(s: dict) -> str:
    lines = ["generation_readiness:"]
    for k in ("ris_quality", "function_spec_quality", "device_spec_quality"):
        lines.append(f"  {k}: {s[k]}")
    lines.append(f"  backend_bare_metal_ready: {s['backend_bare_metal_ready']}")
    lines.append(f"  backend_linux_ready: {s['backend_linux_ready']}")
    if s["blockers"]:
        lines.append("  blockers:")
        for b in s["blockers"]:
            lines.append(f"    - {b}")
    else:
        lines.append("  blockers: []")
    return "\n".join(lines)
