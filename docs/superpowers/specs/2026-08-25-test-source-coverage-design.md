# Generic Test-Source Coverage Design

## Goal

Make subsystem-test evidence auditable for every driver profile. The runtime
must reconcile the tests declared by a manifest with the tests reported by the
guest, preserve provider and test-kind identity, and expose missing or
unexpected evidence without adding bus-specific logic.

## Scope

This change covers the common report contract and the QEMU profile runtime
consumer. It does not add new hardware fixtures or claim whole-subsystem
coverage. Existing `native`, `kselftest`, `tool`, and `kunit` providers remain
manifest-owned and continue to be validated by the provider catalog.

## Data Flow

```text
manifest.test.subsystem.tests
  + guest subsystem-test markers
  -> declared/observed reconciliation
  -> test-source report
  -> subsystem/transaction/transfer capability rows
  -> accepted | failed | inconclusive
```

Each declared test is matched by its stable `name`. The report records its
declared `kind`, `provider`, and `required` flag together with observed status
and return code. A required test is accepted only when the guest reports
`status=pass`, `success=true`, and `return_code=0`. Missing, malformed, or
unexpected evidence is never silently treated as success.

## Report Contract

The report is JSON-compatible:

```json
{
  "status": "accepted",
  "declared": {
    "total": 2,
    "required": 1,
    "optional": 1,
    "by_kind": {"native": 1, "tool": 1},
    "by_provider": {"linux-i2c-dev": 1}
  },
  "observed": {"total": 2, "names": ["i2c-transaction", "linux-i2c-dev-tool"]},
  "tests": [],
  "missing_required": [],
  "failed_required": [],
  "inconclusive_required": [],
  "unexpected_observed": [],
  "optional_failures": []
}
```

Report status is `failed` when a required test explicitly fails; it is
`inconclusive` when required evidence is missing, malformed, skipped, or
unexpected. Optional failures are retained in `optional_failures` but do not
block acceptance. Duplicate declared or observed names are reported as
inconclusive evidence rather than being arbitrarily merged.

## Capability Integration

`QemuProfileRuntime` consumes the report once. `subsystem`, `transaction`, and
`transfer` rows use the report status only when those capabilities are
declared by the manifest. The raw report is retained in both the runtime
result and its payload. Registration, probe, unload, and trace handling remain
independent capability producers.

## Security and Failure Policy

The report builder consumes structured manifest objects and parsed guest
records only. It does not execute commands, infer providers from executable
paths, or accept a guest test name that was not declared. Provider path and
kernel-module validation remains in `experiment_manifest.py` and
`subsystem_providers.py`.

## Verification

Unit tests will prove required pass, required failure, missing evidence,
unexpected evidence, optional failure, duplicate names, and preservation of
provider/kind metadata. Existing profile runtime tests will prove capability
mapping uses the strict report. The existing QEMU profile matrix remains the
runtime regression and must continue to report the same seven accepted
profiles.
