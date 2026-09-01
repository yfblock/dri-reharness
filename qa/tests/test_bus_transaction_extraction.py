from __future__ import annotations

from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from extractor import ExtractorConfig, extract_ris  # noqa: E402
from extractor.formal import walk_leaf_ops  # noqa: E402
from extractor.metrics import score  # noqa: E402
from backends.oracles.transaction_ir_oracle import verify_transaction_source  # noqa: E402


def _transaction_rows(source: Path) -> list[dict]:
    result = extract_ris(ExtractorConfig(source=str(source)))
    rows = []
    for module in result.formal["modules"]:
        for op in walk_leaf_ops(module["ops"]):
            body = op.get("TransactionRead")
            if body is not None:
                rows.append(body)
    return rows


def test_i2c_transfer_is_preserved_as_message_transaction():
    rows = _transaction_rows(
        _paths.REPO_ROOT / "benchmarks/drivers/fixtures/reharness-i2c-sensor.c")

    assert len(rows) == 1
    row = rows[0]
    assert row["transport"] == "i2c"
    assert row["protocol"] == "i2c_transfer"
    assert row["target"] == {"Var": "client->adapter"}
    assert row["selector"] == {"Var": "messages"}
    assert row["payload"]["Message"]["message"] == {"Var": "messages"}
    assert row["payload"]["Message"]["count"] == {"Var": "ARRAY_SIZE(messages)"}


def test_spi_sync_is_preserved_as_message_transaction():
    rows = _transaction_rows(
        _paths.REPO_ROOT / "benchmarks/drivers/fixtures/reharness-spi-sensor.c")

    assert len(rows) == 1
    row = rows[0]
    assert row["transport"] == "spi"
    assert row["protocol"] == "spi_sync"
    assert row["target"] == {"Var": "spi"}
    assert row["selector"] == {"Var": "&message"}
    assert row["payload"]["Message"]["message"] == {"Var": "&message"}


def test_transaction_only_driver_is_not_rejected_as_missing_mmio():
    source = _paths.REPO_ROOT / "benchmarks/drivers/fixtures/reharness-spi-sensor.c"
    result = extract_ris(ExtractorConfig(source=str(source)))
    validation = verify_transaction_source(result.formal, str(source))
    result.formal.setdefault("metadata", {})["transaction_validation"] = validation

    readiness = score(result.device_spec, result.formal,
                      result.warnings, result.facts)

    assert validation["coverage_complete"] is True
    assert result.stats["transactions"] == 1
    assert not any("no MMIO register accesses" in item
                   for item in readiness["blockers"])
    assert readiness["llm_synthesis_ready"] is True
