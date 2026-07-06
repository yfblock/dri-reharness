"""reharness extractor — libclang AST + dataflow/taint RIS extraction.

Produces RIS JSON compatible with driver-harness (src/ir/mod.rs schema).
"""
from .tu import parse_translation_unit, locate_libclang
from .extractor import extract_ris, ExtractorConfig

__all__ = ["parse_translation_unit", "locate_libclang", "extract_ris", "ExtractorConfig"]
