"""Typed, repository-scoped experiment manifests.

The manifest is deliberately small and data-only.  Keeping validation here
means orchestration code can consume a trusted object instead of repeatedly
interpreting loosely typed JSON dictionaries.

Split into layered modules (validators/specs/parsers/validate/serialize);
every name previously importable from ``experiment_manifest`` is
re-exported here.
"""
from __future__ import annotations

from .validators import (  # noqa: F401
    ManifestError, ManifestValidationError,
    _TOP_FIELDS, _SOURCE_FIELDS, _COMPILE_FIELDS, _RUNTIME_FIELDS,
    _PCI_FIELDS, _SAFETY_FIELDS, _QEMU_FIELDS, _QEMU_BINDING_FIELDS,
    _CAPABILITY_FIELDS, _REGISTRATION_FIELDS, _REGISTRATION_IDENTITY_FIELDS,
    _SUBSYSTEM_CONTRACT_FIELDS, _SUBSYSTEM_CONTRACT_REQUIRED_FIELDS,
    _FIXTURE_FIELDS, _TEST_FIELDS, _SUBSYSTEM_FIELDS,
    _SUBSYSTEM_TEST_FIELDS, _COVERAGE_FIELDS, _TRACE_FIELDS, _LIMIT_FIELDS,
    _TRACE_EVENT_FIELDS, _TRACE_KINDS, _KNOWN_CAPABILITIES,
    _unknown, _required, _string, _integer, _repo_root, _inside_repo,
    _hex_digest,
)
from .specs import (  # noqa: F401
    SourceSpec, CompileSpec, PciIdentity, SafetyPolicy, RuntimeCapabilities,
    RegistrationContract, RuntimeFixture, QemuPolicy, QemuBinding,
    RuntimeSpec, SubsystemTestSpec, SubsystemTestSuite, CoverageSpec,
    TestSpec, TraceSpec, IterationLimits, ExperimentManifest,
)
from .parsers import (  # noqa: F401
    _parse_mask, _parse_pci_value, _parse_safety, _parse_capabilities,
    _parse_registration_contract, _parse_subsystem_contracts,
    _parse_qemu_binding, _json_config, _parse_fixture, _parse_coverage,
)
from .validate import validate_manifest  # noqa: F401
from .serialize import (  # noqa: F401
    _json_value, canonical_json, canonical_manifest_json, manifest_digest,
    canonical_digest, load_manifest, validate_trace_fields,
)
