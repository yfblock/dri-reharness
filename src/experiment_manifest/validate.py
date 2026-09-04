"""validate_manifest: full-manifest validation entry point."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from subsystem_providers import ProviderCatalogError, load_provider_catalog

from .validators import (
    ManifestError, _unknown, _required, _string, _integer, _repo_root,
    _inside_repo, _hex_digest, _TOP_FIELDS, _SOURCE_FIELDS, _COMPILE_FIELDS,
    _RUNTIME_FIELDS, _PCI_FIELDS, _SAFETY_FIELDS, _QEMU_FIELDS,
    _TEST_FIELDS, _SUBSYSTEM_FIELDS, _SUBSYSTEM_TEST_FIELDS,
    _TRACE_FIELDS, _LIMIT_FIELDS, _TRACE_EVENT_FIELDS,
)
from .specs import (
    CompileSpec, ExperimentManifest, IterationLimits, PciIdentity,
    QemuPolicy, RuntimeSpec, SourceSpec, SubsystemTestSpec,
    SubsystemTestSuite, TestSpec, TraceSpec,
)
from .parsers import (
    _parse_mask, _parse_pci_value, _parse_safety, _parse_capabilities,
    _parse_registration_contract, _parse_subsystem_contracts,
    _parse_qemu_binding, _parse_fixture, _parse_coverage,
)


def validate_manifest(document: Mapping[str, Any], *, repo_root: str | os.PathLike[str] | Path | None = None,
                      manifest_dir: str | os.PathLike[str] | Path | None = None) -> ExperimentManifest:
    if not isinstance(document, Mapping):
        raise ManifestError("manifest must be a JSON object")
    _unknown(document, _TOP_FIELDS, "manifest")
    _required(document, _TOP_FIELDS, "manifest")
    schema = _integer(document["schema"], "schema", minimum=1)
    if schema != 2:
        raise ManifestError(f"unsupported manifest schema: {schema}")
    name = _string(document["name"], "name")
    root = Path(repo_root).resolve() if repo_root is not None else _repo_root(Path.cwd())
    base = Path(manifest_dir).resolve() if manifest_dir is not None else root

    source_doc = document["source"]
    if isinstance(source_doc, str):
        source_doc = {"path": source_doc}
    if not isinstance(source_doc, Mapping):
        raise ManifestError("source must be an object")
    _unknown(source_doc, _SOURCE_FIELDS, "source")
    _required(source_doc, {"path"}, "source")
    source_path = _inside_repo(source_doc["path"], root, "source.path")
    # Relative paths are repository-relative; accepting a manifest-local path
    # when it exists keeps temporary and generated manifests convenient.
    if not source_path.exists() and not Path(str(source_doc["path"])).is_absolute():
        local = (base / str(source_doc["path"])).resolve()
        try:
            local.relative_to(root)
        except ValueError:
            pass
        else:
            source_path = local
    source = SourceSpec(source_path, _hex_digest(source_doc.get("sha256"), "source.sha256"))

    compile_doc = document["compile"]
    if not isinstance(compile_doc, Mapping):
        raise ManifestError("compile must be an object")
    _unknown(compile_doc, _COMPILE_FIELDS, "compile")
    _required(compile_doc, _COMPILE_FIELDS, "compile")
    compile_spec = CompileSpec(*(_string(compile_doc[field], f"compile.{field}") for field in ("backend", "language", "context")))

    runtime_doc = document["runtime"]
    if not isinstance(runtime_doc, Mapping):
        raise ManifestError("runtime must be an object")
    _unknown(runtime_doc, _RUNTIME_FIELDS, "runtime")
    _required(runtime_doc, {"adapter", "qemu"}, "runtime")
    qemu_doc = runtime_doc.get("qemu")
    if not isinstance(qemu_doc, Mapping):
        raise ManifestError("runtime.qemu must be an object")
    _unknown(qemu_doc, _QEMU_FIELDS, "runtime.qemu")
    _required(qemu_doc, {"machine", "device", "bus", "module", "timeout_seconds"}, "runtime.qemu")
    qemu_args = qemu_doc.get("qemu_args", [])
    if not isinstance(qemu_args, list) or any(not isinstance(item, str) for item in qemu_args):
        raise ManifestError("runtime.qemu.qemu_args must be a list of strings")
    kernel_modules = qemu_doc.get("kernel_modules", [])
    if (not isinstance(kernel_modules, list)
            or any(not isinstance(item, str) or not item.strip()
                   or re.fullmatch(r"[A-Za-z0-9_.+-]+", item) is None
                   for item in kernel_modules)):
        raise ManifestError(
            "runtime.qemu.kernel_modules must be a list of safe module names")
    launch_device = qemu_doc.get("launch_device", False)
    if not isinstance(launch_device, bool):
        raise ManifestError("runtime.qemu.launch_device must be a boolean")
    probe_pattern = qemu_doc.get("probe_pattern")
    if probe_pattern is not None:
        probe_pattern = _string(probe_pattern, "runtime.qemu.probe_pattern")
        try:
            re.compile(probe_pattern)
        except re.error as exc:
            raise ManifestError("runtime.qemu.probe_pattern is invalid") from exc
    registrar = qemu_doc.get("registrar")
    if registrar is not None:
        registrar = _string(registrar, "runtime.qemu.registrar")
    binding = _parse_qemu_binding(qemu_doc.get("binding"))
    qemu = QemuPolicy(
        machine=_string(qemu_doc["machine"], "runtime.qemu.machine"),
        device=_string(qemu_doc["device"], "runtime.qemu.device"),
        bus=_string(qemu_doc["bus"], "runtime.qemu.bus"),
        module=_string(qemu_doc["module"], "runtime.qemu.module"),
        timeout_seconds=_integer(qemu_doc["timeout_seconds"], "runtime.qemu.timeout_seconds", minimum=1),
        probe_pattern=probe_pattern,
        registrar=registrar,
        qemu_args=tuple(qemu_args),
        kernel_modules=tuple(kernel_modules),
        launch_device=launch_device,
        binding=binding,
    )
    pci_doc = runtime_doc.get("pci_identity")
    if pci_doc is not None:
        if not isinstance(pci_doc, Mapping):
            raise ManifestError("runtime.pci_identity must be an object")
        _unknown(pci_doc, _PCI_FIELDS, "runtime.pci_identity")
        _required(pci_doc, {"vendor", "device"}, "runtime.pci_identity")
        pci = PciIdentity(
            vendor=_parse_pci_value(pci_doc["vendor"], "runtime.pci_identity.vendor"),
            device=_parse_pci_value(pci_doc["device"], "runtime.pci_identity.device"),
            subsystem_vendor=None if pci_doc.get("subsystem_vendor") is None else _parse_pci_value(pci_doc["subsystem_vendor"], "runtime.pci_identity.subsystem_vendor"),
            subsystem_device=None if pci_doc.get("subsystem_device") is None else _parse_pci_value(pci_doc["subsystem_device"], "runtime.pci_identity.subsystem_device"),
            class_code=None if pci_doc.get("class_code") is None else _parse_pci_value(pci_doc["class_code"], "runtime.pci_identity.class_code"),
        )
    else:
        pci = None
    if qemu.bus == "pci" and pci is None:
        raise ManifestError("runtime.pci_identity is required for PCI QEMU policy")
    profile = runtime_doc.get("profile")
    if profile is not None:
        profile = _string(profile, "runtime.profile")
        if re.fullmatch(r"[A-Za-z0-9_.:-]+", profile) is None:
            raise ManifestError("runtime.profile must be a safe profile identifier")
    capabilities = _parse_capabilities(runtime_doc.get("capabilities"))
    fixture = _parse_fixture(runtime_doc.get("fixture"), root)
    subsystem_contracts = _parse_subsystem_contracts(
        runtime_doc.get("subsystem_contracts"))
    registration = _parse_registration_contract(
        runtime_doc.get("registration"))
    try:
        provider_registry = load_provider_catalog(root)
    except ProviderCatalogError as exc:
        raise ManifestError(str(exc)) from exc
    runtime = RuntimeSpec(
        adapter=_string(runtime_doc["adapter"], "runtime.adapter"),
        qemu=qemu,
        pci_identity=pci,
        safety_policy=_parse_safety(runtime_doc.get("safety_policy")),
        profile=profile,
        capabilities=capabilities,
        fixture=fixture,
        subsystem_contracts=subsystem_contracts,
        registration=registration,
    )

    test_doc = document["test"]
    if not isinstance(test_doc, Mapping):
        raise ManifestError("test must be an object")
    _unknown(test_doc, _TEST_FIELDS, "test")
    subsystem_doc = test_doc.get("subsystem")
    if "executable" not in test_doc and subsystem_doc is None:
        raise ManifestError("test requires executable or subsystem")
    args = test_doc.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ManifestError("test.args must be a list of strings")
    actions = test_doc.get("actions", [])
    if not isinstance(actions, list) or any(not isinstance(item, Mapping) for item in actions):
        raise ManifestError("test.actions must be a list of objects")
    executable = None
    if "executable" in test_doc:
        executable = _inside_repo(test_doc["executable"], root, "test.executable")
        if not executable.exists() and not Path(str(test_doc["executable"])).is_absolute():
            local = (base / str(test_doc["executable"])).resolve()
            try:
                local.relative_to(root)
            except ValueError:
                pass
            else:
                executable = local
    success_pattern = test_doc.get("success_pattern")
    if success_pattern is not None:
        success_pattern = _string(success_pattern, "test.success_pattern")

    subsystem = None
    if subsystem_doc is not None:
        if not isinstance(subsystem_doc, Mapping):
            raise ManifestError("test.subsystem must be an object")
        _unknown(subsystem_doc, _SUBSYSTEM_FIELDS, "test.subsystem")
        _required(subsystem_doc, _SUBSYSTEM_FIELDS, "test.subsystem")
        subsystem_name = _string(subsystem_doc["name"], "test.subsystem.name")
        subsystem_tests = subsystem_doc["tests"]
        if (not isinstance(subsystem_tests, list) or not subsystem_tests
                or any(not isinstance(item, Mapping) for item in subsystem_tests)):
            raise ManifestError("test.subsystem.tests must be a non-empty list of objects")
        parsed_tests: list[SubsystemTestSpec] = []
        for index, item in enumerate(subsystem_tests):
            field = f"test.subsystem.tests[{index}]"
            _unknown(item, _SUBSYSTEM_TEST_FIELDS, field)
            _required(item, {"name"}, field)
            test_name = _string(item["name"], f"{field}.name")
            kind_declared = "kind" in item
            test_kind = item.get("kind", "native")
            if not isinstance(test_kind, str) or test_kind not in {
                    "native", "kselftest", "kunit", "tool"}:
                raise ManifestError(
                    f"{field}.kind must be native, kselftest, kunit, or tool")
            test_provider = item.get("provider")
            if test_provider is not None:
                test_provider = _string(test_provider, f"{field}.provider")
                if re.fullmatch(r"[A-Za-z0-9_.+-]+", test_provider) is None:
                    raise ManifestError(f"{field}.provider is unsafe")
            test_required = item.get("required", True)
            if not isinstance(test_required, bool):
                raise ManifestError(f"{field}.required must be a boolean")
            test_module = item.get("module")
            test_args = item.get("args", [])
            if (not isinstance(test_args, list)
                    or any(not isinstance(value, str) for value in test_args)):
                raise ManifestError(f"{field}.args must be a list of strings")
            args_declared = "args" in item
            test_success = item.get("success_pattern")
            if test_success is not None:
                test_success = _string(test_success, f"{field}.success_pattern")
                try:
                    re.compile(test_success)
                except re.error as exc:
                    raise ManifestError(
                        f"{field}.success_pattern is invalid") from exc

            test_executable = None
            if "executable" in item:
                test_executable = _inside_repo(
                    item["executable"], root, f"{field}.executable")
                if (not test_executable.exists()
                        and not Path(str(item["executable"])).is_absolute()):
                    local = (base / str(item["executable"])).resolve()
                    try:
                        local.relative_to(root)
                    except ValueError:
                        pass
                    else:
                        test_executable = local

            declared_modules = set(qemu.kernel_modules)
            if fixture is not None:
                declared_modules.update(fixture.kernel_modules)
                declared_modules.update(
                    Path(path).stem for path in fixture.module_sources)
            try:
                resolved_provider = provider_registry.resolve_test(
                    test_provider,
                    subsystem=subsystem_name,
                    declared_kind=test_kind if kind_declared else None,
                    declared_executable=test_executable,
                    declared_module=test_module,
                    declared_args=tuple(test_args),
                    args_declared=args_declared,
                    declared_success_pattern=test_success,
                    success_declared="success_pattern" in item,
                    available_kernel_modules=declared_modules,
                    field=field,
                )
            except ProviderCatalogError as exc:
                raise ManifestError(str(exc)) from exc
            if resolved_provider is not None:
                test_kind = resolved_provider.kind
                test_executable = resolved_provider.executable
                test_module = resolved_provider.module
                test_args = list(resolved_provider.args)
                test_success = resolved_provider.success_pattern

            if test_kind == "kunit":
                if "executable" in item:
                    raise ManifestError(
                        f"{field}.kunit must not declare executable")
                test_module = _string(test_module, f"{field}.module")
                if re.fullmatch(r"[A-Za-z0-9_.+-]+", test_module) is None:
                    raise ManifestError(f"{field}.module is unsafe")
                if test_module not in declared_modules:
                    raise ManifestError(
                        f"{field}.module must be declared in runtime kernel_modules")
                test_executable = None
            elif test_executable is None:
                if test_provider is None:
                    raise ManifestError(
                        f"{field} requires executable for {test_kind} test")
                # Provider test the catalog could not resolve (empty catalog
                # at this root): deferred — the pipeline resolves or skips.
            if test_kind == "kunit" and test_success is None:
                raise ManifestError(
                    f"{field}.success_pattern is required for kunit test")
            raw_assets = item.get("assets", [])
            if (not isinstance(raw_assets, list)
                    or any(not isinstance(value, str) or not value.strip()
                           for value in raw_assets)):
                raise ManifestError(f"{field}.assets must be a list of paths")
            assets = tuple(_inside_repo(value, root, f"{field}.assets")
                           for value in raw_assets)
            parsed_tests.append(SubsystemTestSpec(
                name=test_name, executable=test_executable, kind=test_kind,
                module=test_module, args=tuple(test_args),
                success_pattern=test_success, assets=assets,
                provider=test_provider, required=test_required))
        subsystem = SubsystemTestSuite(subsystem_name, tuple(parsed_tests))
    if subsystem is not None:
        # Subsystem tests replace the native exerciser: no dual dispatch.
        executable = None
    coverage = _parse_coverage(test_doc.get("coverage"))
    test = TestSpec(executable, tuple(args), tuple(dict(item) for item in actions),
                    success_pattern, subsystem, coverage)

    trace_doc = document["trace"]
    if not isinstance(trace_doc, Mapping):
        raise ManifestError("trace must be an object")
    _unknown(trace_doc, _TRACE_FIELDS, "trace")
    _required(trace_doc, {"fields"}, "trace")
    fields = trace_doc["fields"]
    if not isinstance(fields, list) or not fields or any(item not in _TRACE_EVENT_FIELDS for item in fields):
        raise ManifestError("trace.fields contains invalid trace field")
    if len(set(fields)) != len(fields):
        raise ManifestError("trace.fields must not contain duplicates")
    required_trace = {"phase", "function", "kind", "width_bits", "address", "value", "sequence"}
    if not required_trace.issubset(fields):
        raise ManifestError("trace.fields missing required trace field")
    trace = TraceSpec(
        tuple(fields),
        None if trace_doc.get("value_mask") is None else _parse_mask(trace_doc["value_mask"], "trace.value_mask"),
        None if trace_doc.get("address_mask") is None else _parse_mask(trace_doc["address_mask"], "trace.address_mask"),
        trace_doc.get("normalize_function", True),
    )
    if not isinstance(trace.normalize_function, bool):
        raise ManifestError("trace.normalize_function must be boolean")
    instrument = trace_doc.get("instrument", False)
    if not isinstance(instrument, bool):
        raise ManifestError("trace.instrument must be boolean")
    exercised_calls = trace_doc.get("exercised_calls", [])
    if not isinstance(exercised_calls, list) or any(not isinstance(item, str) or not item.strip() for item in exercised_calls):
        raise ManifestError("trace.exercised_calls must be a list of non-empty strings")
    trace = TraceSpec(trace.fields, trace.value_mask, trace.address_mask,
                      trace.normalize_function, instrument, tuple(exercised_calls))

    limits_doc = document["limits"]
    if not isinstance(limits_doc, Mapping):
        raise ManifestError("limits must be an object")
    _unknown(limits_doc, _LIMIT_FIELDS, "limits")
    _required(limits_doc, {"compile", "runtime", "trace"}, "limits")
    values = {field: _integer(limits_doc[field], f"limits.{field}", minimum=1) for field in ("compile", "runtime", "trace")}
    if "total" in limits_doc:
        values["total"] = _integer(limits_doc["total"], "limits.total", minimum=1)
    limits = IterationLimits(**values)
    return ExperimentManifest(schema, name, source, compile_spec, runtime, test, trace, limits, root, dict(document))


