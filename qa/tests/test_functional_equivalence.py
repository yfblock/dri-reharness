from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backends.llm_bridge import build_evidence_json, _modules_ris_text
from extractor.extractor import ExtractorConfig, extract_ris
from extractor.formal import walk_leaf_ops


class FunctionalEvidenceTests(unittest.TestCase):
    def test_state_writes_are_preserved_in_llm_evidence(self):
        formal = {
            "driver": "demo",
            "register_map": [],
            "modules": [{
                "name": "writer",
                "ops": [{
                    "StateWrite": {
                        "field": "dws->tx",
                        "value": {
                            "BinOp": {
                                "op": "Add",
                                "left": {"Var": "dws->tx"},
                                "right": {"Var": "dws->n_bytes"},
                            }
                        },
                        "width": "Unknown",
                    }
                }],
            }],
        }
        device_spec = type("DeviceSpec", (), {"name": "demo", "cls": "spi"})()
        bind = type(
            "Bind",
            (),
            {
                "primitives": [],
                "types": [],
                "state": [],
                "callbacks": [],
                "includes": [],
            },
        )()

        evidence = json.loads(build_evidence_json(formal, device_spec, bind))
        self.assertEqual(evidence["modules"], ["writer"])

        ris_text = _modules_ris_text(formal)
        self.assertIn("STATE(dws->tx) := (dws->tx + dws->n_bytes)", ris_text)

    def test_driver_state_assignments_are_extracted(self):
        source_text = r"""
struct state {
    unsigned char *tx;
    unsigned int tx_len;
    unsigned int n_bytes;
    void *base;
};
extern void writel(unsigned int value, void *address);

static void writer(struct state *dws)
{
    unsigned int txw = *(unsigned char *)dws->tx;
    writel(txw, dws->base);
    dws->tx += dws->n_bytes;
    --dws->tx_len;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state_driver.c"
            source.write_text(source_text, encoding="utf-8")
            result = extract_ris(ExtractorConfig(
                source=str(source), compile_context_mode="off"))

        state_writes = []
        for module in result.formal["modules"]:
            for op in walk_leaf_ops(module["ops"]):
                if "StateWrite" in op:
                    state_writes.append(op["StateWrite"])

        fields = {op["field"] for op in state_writes}
        self.assertIn("dws->tx", fields)
        self.assertIn("dws->tx_len", fields)

    def test_tx_value_is_bound_before_pointer_advance(self):
        source_text = r"""
struct state {
    unsigned char *tx;
    unsigned int tx_len;
    unsigned int n_bytes;
    void *base;
};
extern void writel(unsigned int value, void *address);

static void writer(struct state *dws)
{
    unsigned int txw = *(unsigned char *)dws->tx;
    dws->tx += dws->n_bytes;
    writel(txw, dws->base);
    --dws->tx_len;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "tx_driver.c"
            source.write_text(source_text, encoding="utf-8")
            result = extract_ris(ExtractorConfig(
                source=str(source), compile_context_mode="off"))

        ops = list(walk_leaf_ops(result.formal["modules"][0]["ops"]))
        kinds = [next(iter(op)) for op in ops]
        self.assertEqual(kinds, ["ValueBind", "StateWrite", "Write", "StateWrite"])
        self.assertEqual(ops[0]["ValueBind"]["var"], "txw")
        self.assertEqual(ops[2]["Write"]["value"], {"Var": "txw"})

    def test_rx_buffer_write_precedes_pointer_advance(self):
        source_text = r"""
struct state {
    unsigned char *rx;
    unsigned int rx_len;
    void *base;
};
extern unsigned int readl(void *address);

static void reader(struct state *dws)
{
    unsigned int rxw = readl(dws->base);
    *(unsigned char *)dws->rx = rxw;
    dws->rx += 1;
    --dws->rx_len;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rx_driver.c"
            source.write_text(source_text, encoding="utf-8")
            result = extract_ris(ExtractorConfig(
                source=str(source), compile_context_mode="off"))

        ops = list(walk_leaf_ops(result.formal["modules"][0]["ops"]))
        kinds = [next(iter(op)) for op in ops]
        self.assertEqual(kinds, ["Read", "OutputWrite", "StateWrite", "StateWrite"])
        self.assertEqual(ops[1]["OutputWrite"]["target"], "*(unsigned char *)dws->rx")
        self.assertEqual(ops[1]["OutputWrite"]["value"], {"Var": "rxw"})

    def test_nested_mmio_read_is_emitted_before_buffer_output(self):
        source_text = r"""
struct state {
    unsigned char *rx;
    void *base;
};
extern unsigned int readl(void *address);

static void reader(struct state *dws)
{
    *(unsigned char *)dws->rx = readl(dws->base);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nested_rx_driver.c"
            source.write_text(source_text, encoding="utf-8")
            result = extract_ris(ExtractorConfig(
                source=str(source), compile_context_mode="off"))

        ops = list(walk_leaf_ops(result.formal["modules"][0]["ops"]))
        self.assertEqual([next(iter(op)) for op in ops],
                         ["Read", "OutputWrite"])
        self.assertEqual(ops[1]["OutputWrite"]["value"],
                         {"Var": "buffer_read_0"})


if __name__ == "__main__":
    unittest.main()
