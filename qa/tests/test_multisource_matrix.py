from pathlib import Path

try:
    from . import _bootstrap as _paths  # noqa: F401
except ImportError:
    import _bootstrap as _paths  # noqa: F401


def test_multisource_matrix_accepts_headers_and_two_c_translation_units():
    from verification.run_multisource_matrix import (
        _kbuild_contains_sources, _load_manifest, _source_mmio_counts)

    root = Path(__file__).resolve().parents[2]
    manifest, sources, kbuild = _load_manifest(
        str(root / "benchmarks/drivers/multisource/dw-apb-ssi-full.json"))

    assert manifest["name"] == "dw-apb-ssi-full"
    assert len(sources) == 3
    assert any(source.endswith(".h") for source in sources)
    assert not kbuild
    assert _kbuild_contains_sources(
        str(root / "vendor/linux/drivers/spi/Makefile"), sources)
    assert _source_mmio_counts(sources)["total"] > 0


def test_multisource_matrix_skips_original_kbuild_when_manifest_has_none(tmp_path):
    from verification.run_multisource_matrix import _compile_original_kbuild

    result = _compile_original_kbuild(
        {"name": "header-only-kbuild"}, "", str(tmp_path))

    assert result == {
        "attempted": False,
        "success": False,
        "reason": "manifest has no module-level kbuild",
    }


def test_multisource_matrix_accepts_single_manifest_path():
    from verification.run_multisource_matrix import _manifest_paths

    root = Path(__file__).resolve().parents[2]
    manifest = root / "benchmarks/drivers/multisource/dw-apb-ssi-full.json"

    assert _manifest_paths(str(manifest)) == [str(manifest)]
