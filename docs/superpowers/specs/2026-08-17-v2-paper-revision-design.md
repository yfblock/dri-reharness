# v2 Paper Revision Design

## Goal

Make `research/paper/v2/` internally consistent, evidence-bounded, reproducible as a paper artifact, and explicit about experiments that still require new system runs.

## Scope

This pass revises prose, tables, references, and paper metadata only. It does not change extractor/verifier behavior, regenerate experiment numbers, or claim new LLM/system results. Missing evidence is recorded in a machine-readable-looking, human-readable experiment-debt section rather than filled by inference.

## Boundaries

- `sections_3_5.tex`: describe RIS as a structured evidence IR unless formal semantics are actually present; align AST/IR merge and receipt claims with the implementation.
- `sections_6_8.tex`: separate deterministic baseline, LLM case study, and synthesis eligibility; state what each oracle does not prove; add an explicit experiment-debt subsection.
- `sections_9_11.tex`: rewrite limitations/conclusion to match the bounded evidence; repair bibliography metadata and remove unverifiable placeholder citations.
- `sections_1_2.tex` and `main.tex`: narrow abstract/introduction/contribution language without changing the measured macros.
- `generated_results.tex`: change only labels/captions if needed for semantic clarity; do not alter measured values.

## Acceptance criteria

1. No statement claims that the gate rejects extra accesses, verifies guards/value expressions, or proves whole-driver equivalence unless the current artifact actually does so.
2. LLM results are explicitly labeled as one non-repeated DesignWare artifact case; deterministic 19-driver results are never presented as LLM success rates.
3. Every deferred experiment has an owner-independent description of required evidence, affected claim, and why it cannot be inferred from current artifacts.
4. References are verifiable or removed; no placeholder authors or fake metadata remain.
5. The v2 PDF builds with no undefined references/citations; remaining layout warnings are reported rather than hidden.
