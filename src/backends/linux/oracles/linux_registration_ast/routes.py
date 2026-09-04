"""Route proofs: registered callback targets derived from the collected AST."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from .context import _call_policy
from .support import (
    _path_key,
    _path_parent_key,
    _path_table,
    _resolve_local_aliases,
    registration_route_fingerprint,
)


def _registered_routes(
        ast: dict, source: Path,
        registration_policy: Mapping[str, Any]
        ) -> tuple[list[dict], list[dict]]:
    _resolve_local_aliases(ast)
    bindings = ast["bindings"]
    call_results = ast["call_results"]
    calls = ast["calls"]
    module_init_targets = set(ast["module_init_targets"])
    errors: list[dict] = []
    object_proofs: dict[tuple, dict] = {}
    routes: list[dict] = []

    root_calls = []
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] not in {"driver_root", "object_root"}:
            continue
        if call["function_usr"] not in module_init_targets:
            problems.append("driver registration is not referenced by module_init")
        if problems:
            errors.append({"kind": "invalid_root_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        key = _path_key(owner)
        proof = {
            "object": owner,
            "kind": policy["kind"],
            "table": policy["table"],
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[key] = proof
        root_calls.append((policy, owner, call, proof))

    # Root-table callback targets (notably probe) become registered only when
    # the exact table object is the module_init registration argument.
    registered_probe_usrs: set[str] = set()
    registered_remove_usrs: set[str] = set()
    for binding in bindings:
        key = _path_key(binding["owner"])
        proof = object_proofs.get(key)
        if (proof and binding["kind"] == "initializer"
                and binding["table"] == proof["table"]
                and binding["signature_matches"]):
            route = {
                "callback": f"{binding['table']}.{binding['field']}",
                "target_usr": binding["target_usr"],
                "target": binding["target"],
                "binding": binding,
                "registration": proof,
                "runtime_entry_registered": True,
            }
            routes.append(route)
            if (proof["kind"] == "driver_root"
                    and binding["field"] == "probe"):
                registered_probe_usrs.add(binding["target_usr"])
            if (proof["kind"] == "driver_root"
                    and binding["field"] == "remove"):
                registered_remove_usrs.add(binding["target_usr"])

    # Straight-line GPIO registration is accepted only from a probe already
    # proven by the root driver chain.
    gpio_sinks: list[tuple[dict, dict, dict]] = []
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] != "gpio_chip":
            continue
        if call["function_usr"] not in registered_probe_usrs:
            problems.append("GPIO registration is outside a registered probe")
        if problems:
            errors.append({"kind": "invalid_gpio_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        proof = {
            "object": owner,
            "kind": "gpio_chip",
            "table": "gpio_chip",
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registered_probe",
                       "function_usr": call["function_usr"]},
                      {"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[_path_key(owner)] = proof
        gpio_sinks.append((owner, call, proof))

    # A misc device is a public registration sink for file_operations.  Keep
    # the proof tied to a registered probe and the exact miscdevice identity;
    # the fops callback table is linked below through its typed field.
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] != "miscdevice":
            continue
        if call["function_usr"] not in registered_probe_usrs:
            problems.append("miscdevice registration is outside a registered probe")
        if problems:
            errors.append({"kind": "invalid_misc_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        proof = {
            "object": owner,
            "kind": "miscdevice",
            "table": "miscdevice",
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registered_probe",
                       "function_usr": call["function_usr"]},
                      {"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[_path_key(owner)] = proof

    # Other framework objects can be registered from a proven probe and then
    # lead through typed pointer fields to their callback table.  Clock v1 is
    # the first such sink; SDHCI/USB reuse the same typed object-flow below.
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] not in {"clk_hw"}:
            continue
        if call["function_usr"] not in registered_probe_usrs:
            problems.append(
                f"{policy['kind']} registration is outside a registered probe")
        if problems:
            errors.append({"kind": "invalid_framework_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        proof = {
            "object": owner,
            "kind": policy["kind"],
            "table": policy["table"],
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registered_probe",
                       "function_usr": call["function_usr"]},
                      {"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[_path_key(owner)] = proof

    link_tables = registration_policy["link_tables"]
    changed = True
    while changed:
        changed = False
        for edge in ast["pointer_edges"]:
            dst_key = _path_key(edge.get("dst"))
            proof = object_proofs.get(dst_key)
            if proof is None:
                proof = object_proofs.get(_path_parent_key(edge.get("dst")))
            if proof is None:
                continue
            expected_table = link_tables.get(
                (proof.get("table"), edge.get("field")))
            if expected_table is None or _path_table(
                    edge.get("src"), registration_policy) != \
                    expected_table:
                continue
            if edge.get("kind") == "assignment" and (
                    edge.get("function_usr") != proof.get("function_usr")
                    or edge.get("control_depth")
                    or edge["location"]["offset"] >=
                    proof["registration_offset"]):
                continue
            src_key = _path_key(edge.get("src"))
            if src_key in object_proofs:
                continue
            object_proofs[src_key] = {
                "object": edge["src"],
                "kind": "typed_object_link",
                "table": expected_table,
                "function_usr": proof.get("function_usr"),
                "registration_offset": proof["registration_offset"],
                "chain": [*proof["chain"], {
                    "kind": "typed_object_link",
                    "field": edge.get("field"),
                    "location": edge.get("location"),
                }],
            }
            changed = True

    # SDHCI callbacks become live only after the exact pdata object is passed
    # to sdhci_pltfm_init(), the returned host identity is preserved, and that
    # same host is handed to sdhci_add_host().  device_get_match_data() is
    # accepted only when it is backed by the exact OF table on the registered
    # driver; straight-line and controlled fallback assignments may add only
    # statically typed pdata objects to that finite set.
    calls_by_location = {
        (call["function_usr"], call["location"]["offset"]): call
        for call in calls
    }
    proven_match_tables = [
        proof for proof in object_proofs.values()
        if proof.get("table") == "of_device_id"
    ]
    for add_call in calls:
        if add_call["callee"] not in {"sdhci_add_host", "__sdhci_add_host"}:
            continue
        problems: list[str] = []
        if add_call["callee_in_source"]:
            problems.append("SDHCI add-host callee is shadowed")
        if add_call["function_usr"] not in registered_probe_usrs:
            problems.append("SDHCI add-host is outside a registered probe")
        if add_call["control_depth"]:
            problems.append("SDHCI add-host is under unsupported control flow")
        if (not add_call["arguments"] or add_call["arguments"][0] is None
                or add_call["argument_types"][0] != "struct sdhci_host *"):
            problems.append("SDHCI add-host has no exact host identity")
        if problems:
            errors.append({"kind": "invalid_sdhci_lifecycle",
                           "call": add_call, "errors": problems})
            continue

        host_key = _path_key(add_call["arguments"][0])
        init_results = [
            result for result in call_results
            if result["callee"] == "sdhci_pltfm_init"
            and result["function_usr"] == add_call["function_usr"]
            and _path_key(result["dst"]) == host_key
            and result["location"]["offset"] < add_call["location"]["offset"]
        ]
        if len(init_results) != 1:
            errors.append({
                "kind": "invalid_sdhci_lifecycle", "call": add_call,
                "errors": ["SDHCI host does not have one exact init result"],
            })
            continue
        init_result = init_results[0]
        init_call = calls_by_location.get((
            init_result["function_usr"], init_result["location"]["offset"]))
        if (init_call is None or init_call["callee_in_source"]
                or init_call["control_depth"]
                or len(init_call["arguments"]) < 2
                or init_call["arguments"][1] is None
                or init_call["argument_types"][1]
                != "const struct sdhci_pltfm_data *"):
            errors.append({
                "kind": "invalid_sdhci_lifecycle", "call": add_call,
                "errors": ["SDHCI init call has no exact pdata identity"],
            })
            continue
        intervening_host_writes = [
            item for item in [*call_results, *ast["pointer_edges"]]
            if _path_key(item.get("dst")) == host_key
            and init_result["location"]["offset"]
            < item["location"]["offset"] < add_call["location"]["offset"]
        ]
        if intervening_host_writes:
            errors.append({
                "kind": "invalid_sdhci_lifecycle", "call": add_call,
                "errors": ["SDHCI host identity is overwritten before add"],
            })
            continue

        pdata = init_call["arguments"][1]
        pdata_key = _path_key(pdata)
        pdata_objects: dict[tuple, tuple[dict, list[dict]]] = {}
        if (pdata.get("scope") == "global"
                and _path_table(pdata, registration_policy) == "sdhci_pltfm_data"):
            pdata_objects[pdata_key] = (pdata, [{
                "kind": "direct_pdata_argument",
                "location": init_call["location"],
            }])
        else:
            match_results = [
                result for result in call_results
                if result["callee"] == "device_get_match_data"
                and result["function_usr"] == init_call["function_usr"]
                and _path_key(result["dst"]) == pdata_key
                and result["location"]["offset"]
                < init_call["location"]["offset"]
            ]
            if len(match_results) != 1 or not proven_match_tables:
                problems.append(
                    "SDHCI pdata has no exact registered match-data source")
            else:
                match_result = match_results[0]
                match_call = calls_by_location.get((
                    match_result["function_usr"],
                    match_result["location"]["offset"]))
                if (match_call is None or match_call["callee_in_source"]
                        or match_call["control_depth"]
                        or not match_call["arguments"]
                        or match_call["argument_types"][0]
                        != "const struct device *"):
                    problems.append("invalid device_get_match_data call")
                else:
                    for proof in proven_match_tables:
                        match_key = _path_key(proof["object"])
                        for edge in ast["pointer_edges"]:
                            if (_path_key(edge.get("dst")) != match_key
                                    or edge.get("field") != "data"):
                                continue
                            source_object = edge.get("src")
                            if (_path_table(source_object, registration_policy) !=
                                    "sdhci_pltfm_data"):
                                problems.append(
                                    "OF match data is not SDHCI pdata")
                                continue
                            pdata_objects[_path_key(source_object)] = (
                                source_object,
                                [*proof["chain"], {
                                    "kind": "match_data_edge",
                                    "location": edge["location"],
                                }],
                            )

                    pdata_assignments = [
                        edge for edge in ast["pointer_edges"]
                        if edge.get("kind") == "assignment"
                        and edge.get("function_usr")
                        == init_call["function_usr"]
                        and _path_key(edge.get("dst")) == pdata_key
                        and match_result["location"]["offset"]
                        < edge["location"]["offset"]
                        < init_call["location"]["offset"]
                    ]
                    for edge in pdata_assignments:
                        source_object = edge.get("src")
                        if (source_object.get("scope") != "global"
                                or _path_table(source_object, registration_policy)
                                != "sdhci_pltfm_data"):
                            problems.append(
                                "SDHCI fallback is not static typed pdata")
                            continue
                        pdata_objects[_path_key(source_object)] = (
                            source_object, [{
                                "kind": "finite_pdata_fallback",
                                "location": edge["location"],
                            }])
                    other_pdata_results = [
                        result for result in call_results
                        if result is not match_result
                        and result["function_usr"] == init_call["function_usr"]
                        and _path_key(result.get("dst")) == pdata_key
                        and result["location"]["offset"]
                        < init_call["location"]["offset"]
                    ]
                    if other_pdata_results:
                        problems.append(
                            "SDHCI pdata has an unsupported call-result source")
            if not pdata_objects:
                problems.append("SDHCI pdata finite set is empty")

        if problems:
            errors.append({"kind": "invalid_sdhci_lifecycle",
                           "call": add_call, "errors": problems})
            continue

        lifecycle_tail = [{
            "kind": "sdhci_pltfm_init",
            "location": init_call["location"],
        }, {
            "kind": "sdhci_host_result",
            "object": init_result["dst"],
            "location": init_result["location"],
        }, {
            "kind": "sdhci_add_host",
            "call": add_call["callee"],
            "location": add_call["location"],
        }]
        for source_object, origin_chain in pdata_objects.values():
            object_proofs[_path_key(source_object)] = {
                "object": source_object,
                "kind": "sdhci_lifecycle",
                "table": "sdhci_pltfm_data",
                "function_usr": init_call["function_usr"],
                "registration_offset": add_call["location"]["offset"],
                "chain": [{"kind": "registered_probe",
                           "function_usr": init_call["function_usr"]},
                          *origin_chain, *lifecycle_tail],
            }

    # Propagate lifecycle-proven pdata to its exact ops table.  This pass is
    # separate from the general fixed point because pdata must never become
    # authoritative from match-table reachability alone.
    for edge in ast["pointer_edges"]:
        proof = object_proofs.get(_path_key(edge.get("dst")))
        if (not proof or proof.get("table") != "sdhci_pltfm_data"
                or edge.get("field") != "ops"
                                or _path_table(
                                    edge.get("src"), registration_policy)
                                != "sdhci_ops"):
            continue
        object_proofs[_path_key(edge["src"])] = {
            "object": edge["src"],
            "kind": "typed_object_link",
            "table": "sdhci_ops",
            "function_usr": proof.get("function_usr"),
            "registration_offset": proof["registration_offset"],
            "chain": [*proof["chain"], {
                "kind": "typed_object_link", "field": "ops",
                "location": edge["location"],
            }],
        }

    # Conservative single-instance USB host lifecycle.  The exact hc_driver
    # table must enter usb_create_hcd(), its returned hcd must be stored as the
    # platform drvdata and passed unchanged to usb_add_hcd().  A registered
    # remove callback must recover that drvdata and pass the same local hcd to
    # usb_remove_hcd() followed by usb_put_hcd().
    for add_call in calls:
        if add_call["callee"] != "usb_add_hcd":
            continue
        problems = []
        if (add_call["callee_in_source"] or add_call["control_depth"]
                or add_call["function_usr"] not in registered_probe_usrs
                or not add_call["arguments"]
                or add_call["arguments"][0] is None
                or add_call["argument_types"][0] != "struct usb_hcd *"):
            problems.append("invalid USB HCD add call")
        if problems:
            errors.append({"kind": "invalid_usb_hcd_lifecycle",
                           "call": add_call, "errors": problems})
            continue
        hcd_key = _path_key(add_call["arguments"][0])
        create_results = [
            result for result in call_results
            if result["callee"] in {"usb_create_hcd", "usb_create_shared_hcd"}
            and result["function_usr"] == add_call["function_usr"]
            and _path_key(result["dst"]) == hcd_key
            and result["location"]["offset"] < add_call["location"]["offset"]
        ]
        if len(create_results) != 1:
            errors.append({
                "kind": "invalid_usb_hcd_lifecycle", "call": add_call,
                "errors": ["USB HCD has no unique create result"],
            })
            continue
        create_result = create_results[0]
        create_call = calls_by_location.get((
            create_result["function_usr"],
            create_result["location"]["offset"]))
        if (create_call is None or create_call["callee_in_source"]
                or create_call["control_depth"]
                or not create_call["arguments"]
                or create_call["arguments"][0] is None
                or _path_table(
                    create_call["arguments"][0], registration_policy)
                != "hc_driver"
                or create_call["arguments"][0].get("scope") != "global"):
            errors.append({
                "kind": "invalid_usb_hcd_lifecycle", "call": add_call,
                "errors": ["USB HCD create has no exact static hc_driver"],
            })
            continue
        host_writes = [
            item for item in [*call_results, *ast["pointer_edges"]]
            if _path_key(item.get("dst")) == hcd_key
            and create_result["location"]["offset"]
            < item["location"]["offset"] < add_call["location"]["offset"]
        ]
        set_drvdata = [
            call for call in calls
            if call["callee"] == "platform_set_drvdata"
            and not call["callee_in_source"] and not call["control_depth"]
            and call["function_usr"] == add_call["function_usr"]
            and len(call["arguments"]) >= 2
            and _path_key(call["arguments"][1]) == hcd_key
            and create_result["location"]["offset"]
            < call["location"]["offset"] < add_call["location"]["offset"]
        ]
        teardown = None
        for remove_usr in registered_remove_usrs:
            get_results = [
                result for result in call_results
                if result["callee"] == "platform_get_drvdata"
                and not result["callee_in_source"]
                and result["function_usr"] == remove_usr
                and not result["control_depth"]
            ]
            for get_result in get_results:
                remove_hcd = [
                    call for call in calls
                    if call["callee"] == "usb_remove_hcd"
                    and not call["callee_in_source"]
                    and not call["control_depth"]
                    and call["function_usr"] == remove_usr
                    and call["arguments"]
                    and _path_key(call["arguments"][0])
                    == _path_key(get_result["dst"])
                    and get_result["location"]["offset"]
                    < call["location"]["offset"]
                ]
                put_hcd = [
                    call for call in calls
                    if call["callee"] == "usb_put_hcd"
                    and not call["callee_in_source"]
                    and not call["control_depth"]
                    and call["function_usr"] == remove_usr
                    and call["arguments"]
                    and _path_key(call["arguments"][0])
                    == _path_key(get_result["dst"])
                    and remove_hcd
                    and remove_hcd[0]["location"]["offset"]
                    < call["location"]["offset"]
                ]
                if len(remove_hcd) == 1 and len(put_hcd) == 1:
                    teardown = (get_result, remove_hcd[0], put_hcd[0])
                    break
            if teardown:
                break
        if host_writes or len(set_drvdata) != 1 or teardown is None:
            errors.append({
                "kind": "invalid_usb_hcd_lifecycle", "call": add_call,
                "errors": ["USB HCD identity/storage/teardown proof failed"],
            })
            continue
        get_result, remove_call, put_call = teardown
        table = create_call["arguments"][0]
        object_proofs[_path_key(table)] = {
            "object": table,
            "kind": "usb_hcd_lifecycle",
            "table": "hc_driver",
            "function_usr": add_call["function_usr"],
            "registration_offset": add_call["location"]["offset"],
            "chain": [
                {"kind": "registered_probe",
                 "function_usr": add_call["function_usr"]},
                {"kind": "usb_create_hcd", "location": create_call["location"]},
                {"kind": "platform_set_drvdata",
                 "location": set_drvdata[0]["location"]},
                {"kind": "usb_add_hcd", "location": add_call["location"]},
                {"kind": "registered_remove",
                 "function_usr": remove_call["function_usr"]},
                {"kind": "platform_get_drvdata",
                 "location": get_result["location"]},
                {"kind": "usb_remove_hcd",
                 "location": remove_call["location"]},
                {"kind": "usb_put_hcd", "location": put_call["location"]},
            ],
        }

    # Conservative gadget lifecycle: only a single statically identifiable
    # gadget object is accepted.  It must be added in the registered probe and
    # deleted by the registered remove callback.  An endpoint table is exposed
    # only when an exact ep0 pointer proves that endpoint belongs to the gadget.
    for add_call in calls:
        if add_call["callee"] != "usb_add_gadget_udc":
            continue
        problems = []
        gadget = (add_call["arguments"][1]
                  if len(add_call["arguments"]) > 1 else None)
        if (add_call["callee_in_source"] or add_call["control_depth"]
                or add_call["function_usr"] not in registered_probe_usrs
                or gadget is None
                or _path_table(gadget, registration_policy) != "usb_gadget"
                or gadget.get("scope") != "global"):
            problems.append("invalid or non-static USB gadget add call")
        delete_calls = [
            call for call in calls
            if call["callee"] == "usb_del_gadget_udc"
            and not call["callee_in_source"] and not call["control_depth"]
            and call["function_usr"] in registered_remove_usrs
            and call["arguments"]
            and _path_key(call["arguments"][0]) == _path_key(gadget)
        ] if gadget else []
        if len(delete_calls) != 1:
            problems.append("USB gadget has no exact registered delete")
        if problems:
            errors.append({"kind": "invalid_usb_gadget_lifecycle",
                           "call": add_call, "errors": problems})
            continue
        gadget_proof = {
            "object": gadget,
            "kind": "usb_gadget_lifecycle",
            "table": "usb_gadget",
            "function_usr": add_call["function_usr"],
            "registration_offset": add_call["location"]["offset"],
            "chain": [
                {"kind": "registered_probe",
                 "function_usr": add_call["function_usr"]},
                {"kind": "usb_add_gadget_udc",
                 "location": add_call["location"]},
                {"kind": "registered_remove",
                 "function_usr": delete_calls[0]["function_usr"]},
                {"kind": "usb_del_gadget_udc",
                 "location": delete_calls[0]["location"]},
            ],
        }
        object_proofs[_path_key(gadget)] = gadget_proof
        for edge in ast["pointer_edges"]:
            edge_owner = (_path_key(edge.get("dst"))
                          if edge.get("kind") == "initializer"
                          else _path_parent_key(edge.get("dst")))
            if (edge_owner != _path_key(gadget)
                    or edge.get("field") != "ep0"
                    or _path_table(edge.get("src"), registration_policy)
                    != "usb_ep"):
                continue
            if (edge.get("kind") == "assignment" and (
                    edge.get("function_usr") != add_call["function_usr"]
                    or edge.get("control_depth")
                    or edge["location"]["offset"]
                    >= add_call["location"]["offset"])):
                continue
            object_proofs[_path_key(edge["src"])] = {
                "object": edge["src"], "kind": "usb_gadget_ep0",
                "table": "usb_ep",
                "function_usr": add_call["function_usr"],
                "registration_offset": add_call["location"]["offset"],
                "chain": [*gadget_proof["chain"], {
                    "kind": "usb_gadget_ep0",
                    "location": edge["location"],
                }],
            }

    # USB gadget/endpoint ops links are lifecycle-authoritative only after the
    # add/delete and ownership proofs above have succeeded.
    for edge in ast["pointer_edges"]:
        proof = object_proofs.get(_path_key(edge.get("dst")))
        expected = {
            ("usb_gadget", "ops"): "usb_gadget_ops",
            ("usb_ep", "ops"): "usb_ep_ops",
        }.get((proof.get("table") if proof else None, edge.get("field")))
        if (expected is None
                or _path_table(edge.get("src"), registration_policy) != expected):
            continue
        if edge.get("kind") == "assignment" and (
                edge.get("function_usr") != proof.get("function_usr")
                or edge.get("control_depth")
                or edge["location"]["offset"] >= proof["registration_offset"]):
            continue
        object_proofs[_path_key(edge["src"])] = {
            "object": edge["src"], "kind": "typed_object_link",
            "table": expected,
            "function_usr": proof.get("function_usr"),
            "registration_offset": proof["registration_offset"],
            "chain": [*proof["chain"], {
                "kind": "typed_object_link", "field": edge.get("field"),
                "location": edge["location"],
            }],
        }

    # Static callback tables reached through the typed framework-object graph
    # (PM and clock in v1) are runtime registered just like root tables.
    for binding in bindings:
        proof = object_proofs.get(_path_key(binding.get("owner")))
        if (proof and binding["kind"] == "initializer"
                and binding["table"] == proof.get("table")
                and binding["signature_matches"]):
            routes.append({
                "callback": f"{binding['table']}.{binding['field']}",
                "target_usr": binding["target_usr"],
                "target": binding["target"],
                "binding": binding,
                "registration": proof,
                "runtime_entry_registered": True,
            })

    # Attach an irq_chip to the exact gpio_irq_chip nested in a registered
    # gpio_chip.  Both calls must be straight-line and ordered before the sink.
    for call in calls:
        policy = registration_policy["irq_attach_apis"].get(call["callee"])
        if policy is None or call["function_usr"] not in registered_probe_usrs:
            continue
        if call["callee_in_source"] or call["control_depth"]:
            errors.append({"kind": "invalid_irq_attach", "call": call,
                           "errors": ["shadowed or controlled attach call"]})
            continue
        if max(policy.values()) >= len(call["arguments"]):
            continue
        parent = call["arguments"][policy["parent_arg"]]
        child = call["arguments"][policy["child_arg"]]
        if parent is None or child is None:
            continue
        parent_parent = _path_parent_key(parent)
        sink = next((proof for owner, sink_call, proof in gpio_sinks
                     if _path_key(owner) == parent_parent
                     and sink_call["function_usr"] == call["function_usr"]
                     and call["location"]["offset"]
                     < sink_call["location"]["offset"]), None)
        if sink:
            object_proofs[_path_key(child)] = {
                "object": child,
                "kind": "irq_chip",
                "table": "irq_chip",
                "function_usr": call["function_usr"],
                "registration_offset": sink["registration_offset"],
                "chain": [*sink["chain"], {
                    "kind": "irq_chip_attach", "call": call["callee"],
                    "location": call["location"],
                }],
            }

    # Dynamic callback slots must be the final straight-line assignment before
    # registration of the exact owner object.  Nested gpio_irq_chip fields are
    # owned by the registered gpio_chip object.
    candidates: dict[tuple, list[dict]] = defaultdict(list)
    for binding in bindings:
        if (binding["kind"] not in {"assignment", "initializer"}
                or not binding["signature_matches"]):
            continue
        owner_key = _path_key(binding["owner"])
        proof = object_proofs.get(owner_key)
        if proof is None and binding["table"] == "gpio_irq_chip":
            parent_key = _path_parent_key(binding["owner"])
            proof = object_proofs.get(parent_key)
        if proof is None:
            continue
        if binding["kind"] == "initializer":
            valid_binding_context = binding["owner"].get("scope") == "global"
        else:
            valid_binding_context = (
                binding["function_usr"] == proof["function_usr"])
        if (not valid_binding_context or binding["control_depth"]
                or binding["location"]["offset"]
                >= proof["registration_offset"]):
            continue
        slot = (owner_key, binding["field"], proof["registration_offset"])
        candidates[slot].append({"binding": binding, "proof": proof})
    for rows in candidates.values():
        selected = max(rows, key=lambda item: item["binding"]["location"]["offset"])
        binding, proof = selected["binding"], selected["proof"]
        routes.append({
            "callback": f"{binding['table']}.{binding['field']}",
            "target_usr": binding["target_usr"],
            "target": binding["target"],
            "binding": binding,
            "registration": proof,
            "runtime_entry_registered": True,
        })

    # Direct IRQ registration binds a function argument rather than an owner
    # field.  v1 accepts it only inside a registered probe and from a real
    # external kernel declaration.
    for call in calls:
        policy = registration_policy["direct_irq_apis"].get(call["callee"])
        if policy is None or call["function_usr"] not in registered_probe_usrs:
            continue
        if call["callee_in_source"] or call["control_depth"]:
            continue
        for index in policy["handler_args"]:
            if index >= len(call["argument_functions"]):
                continue
            functions = call["argument_functions"][index]
            if len(functions) != 1:
                continue
            function = functions[0]
            routes.append({
                "callback": "irq_handler.handler",
                "target_usr": function["usr"],
                "target": function["name"],
                "binding": {"kind": "call_argument", "call": call["callee"],
                            "argument": index, "location": call["location"],
                            "signature_matches": True},
                "registration": {
                    "kind": "direct_irq", "function_usr": call["function_usr"],
                    "registration_offset": call["location"]["offset"],
                    "chain": [{"kind": "registered_probe",
                               "function_usr": call["function_usr"]},
                              {"kind": "registration_call",
                               "call": call["callee"],
                               "location": call["location"]}],
                },
                "runtime_entry_registered": True,
            })

    unique_routes: dict[tuple, dict] = {}
    for route in routes:
        key = (
            route.get("callback"), route.get("target_usr"),
            _path_key((route.get("binding") or {}).get("owner")),
            (route.get("registration") or {}).get("kind"),
        )
        unique_routes.setdefault(key, route)
    routes = list(unique_routes.values())
    for route in routes:
        route["route_id"] = registration_route_fingerprint(route)
    return routes, errors
