# Constrained LLM Translation Paper Design

## Goal

Reframe the first two sections and Related Work of the v2 paper around
reharness as a constrained hybrid translation system for device drivers.

## Core Claim

reharness does not delete or rewrite Linux framework glue in the source
driver. It analyzes the complete driver, where framework glue and hardware
logic are interleaved, and extracts the device-core semantics that matter for
translation: register interactions, guards, typed transactions, and software
state/data movement. The resulting RIS/DeviceSpec evidence contract omits
framework code that has no demonstrated effect on those semantics.

The LLM is confined between two deterministic stages:

1. Deterministic AST/IR analysis establishes the translation semantics.
2. The LLM expresses the compact evidence contract in a target language.
3. Deterministic compilation, AST receipts, and trace checks accept or reject
   the candidate.

## Narrative Structure

Introduction presents driver migration as translation and contrasts three
families: C2Rust-style deterministic source translation, direct LLM
translation, and analysis-guided hybrid translation. reharness is positioned
in the third family, with a stricter semantic boundary than systems that give
the model the complete source program.

Motivation explains why deterministic translation preserves Linux-specific
structure, why direct LLM translation gives the model too much semantic
authority, and why extracting device-core semantics reduces the translation
and hallucination surface without modifying the original driver.

Related Work uses the same three-family taxonomy. Driver analysis,
specification-driven synthesis, symbolic execution, and verification are
presented as deterministic foundations used by hybrid translation rather than
as unrelated peer categories.

## Required Terminology

Use `separate`, `extract`, `device-core semantics`, and
`framework-independent evidence contract`. Do not claim that reharness removes
or deletes glue code from the source. Generated targets may be smaller because
they implement the extracted device contract and only the target-specific
adapter required by a backend.

## Scope

Modify only:

- `research/paper/v2/sections_1_2.tex`
- the Related Work portion of `research/paper/v2/sections_9_11.tex`

Preserve Discussion, Conclusion, bibliography, evaluation macros, and all old
paper versions. Recompile `research/paper/v2/main.tex` twice and require no
undefined citations, references, or duplicate labels.
