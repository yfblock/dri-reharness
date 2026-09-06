"""reharness extractor — libclang AST + dataflow/taint RIS extraction.

Produces RIS JSON compatible with driver-harness (src/ir/mod.rs schema).
"""
from ast_analyzer import locate_libclang, parse_translation_unit
from .extractor import extract_ris, ExtractorConfig

__all__ = ["parse_translation_unit", "locate_libclang", "extract_ris", "ExtractorConfig"]
