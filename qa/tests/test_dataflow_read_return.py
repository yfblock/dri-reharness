"""Focused regressions for inlined helper return/read provenance."""
from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap


if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from extractor.extractor import ExtractorConfig, extract_ris
from extractor.formal import expr_display, walk_leaf_ops


def _extract(source: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "read-return.c"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return extract_ris(ExtractorConfig(source=str(path))).formal


def _leaves(formal: dict, module_name: str) -> list[dict]:
    module = next(item for item in formal["modules"]
                  if item["name"] == module_name)
    return list(walk_leaf_ops(module["ops"]))


def test_non_mmio_read_named_return_does_not_capture_last_mmio_read():
    formal = _extract("""
        #define STATUS 0x10
        #define CONTROL 0x14
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        extern void writel(u32 value, void *addr);
        extern int device_property_read_bool(void *dev, const char *name);

        static int property_enabled(void *dev, void *base)
        {
            u32 status = readl(base + STATUS);
            return device_property_read_bool(dev, "enabled");
        }

        void apply_property(void *dev, void *base)
        {
            int retval = property_enabled(dev, base);
            writel(retval, base + CONTROL);
        }
    """)
    leaves = _leaves(formal, "apply_property")
    read = next(op["Read"] for op in leaves if "Read" in op)
    write = next(op["Write"] for op in leaves if "Write" in op)

    # ``device_property_read_bool`` is not an MMIO read.  Its caller result
    # must not steal the unrelated readl result merely because its name
    # contains "read".
    assert read["var"] == "status"
    assert read["evidence"]["callee"] == "readl"
    assert expr_display(write["value"]) == "retval"


def test_proven_mmio_read_wrapper_chain_still_binds_caller_lhs():
    formal = _extract("""
        #define VALUE 0x20
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        extern void writel(u32 value, void *addr);

        static u32 mmio_read_helper(void *base)
        {
            return readl(base + VALUE);
        }

        static u32 local_read_wrapper(void *base)
        {
            u32 result = mmio_read_helper(base);
            return result;
        }

        void update_value(void *base, u32 mask)
        {
            u32 value = local_read_wrapper(base);
            writel(value | mask, base + VALUE);
        }
    """)
    leaves = _leaves(formal, "update_value")
    read = next(op["Read"] for op in leaves if "Read" in op)
    write = next(op["Write"] for op in leaves if "Write" in op)

    assert read["var"] == "value"
    rendered = expr_display(write["value"])
    assert "value" in rendered and "mask" in rendered


def test_single_source_wrapper_closure_matches_transitive_return_provenance():
    formal = _extract("""
        #define STATUS 0x24
        typedef unsigned int u32;
        extern u32 readl(void *addr);

        static u32 read_status(void *base)
        {
            return readl(base + STATUS);
        }

        static u32 read_status_wrapper(void *base)
        {
            u32 result = read_status(base);
            return result;
        }

        u32 consume_status(void *base)
        {
            u32 status = read_status_wrapper(base);
            return status;
        }
    """)
    leaves = _leaves(formal, "consume_status")
    read = next(op["Read"] for op in leaves if "Read" in op)

    assert read["var"] == "status"


def _run_standalone() -> int:
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    passed = failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
