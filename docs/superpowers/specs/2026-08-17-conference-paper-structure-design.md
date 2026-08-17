# Conference Paper Structure Design

## Goal

Reduce the v2 paper from eleven to eight main sections for a twelve-page
conference-paper body while preserving the technical evidence and evaluation.

## Final Structure

1. Introduction
2. Motivation
3. System Design and Evidence Contract
4. Device-Core Contract Extraction
5. Constrained LLM Translation and Verification
6. Evaluation
7. Discussion and Limitations
8. Conclusion

The standalone Related Work section is removed. Its three-way comparison of
deterministic source translation, direct LLM translation, and analysis-guided
LLM translation remains in concise form in the Introduction and Motivation.
All cited works remain in the bibliography.

## Consolidation Rules

Section 3 combines the pipeline overview, RIS language, semantic inference,
DeviceSpec/FunctionSpec, backend bindings, and evidence JSON. It explains the
contract passed across the deterministic-analysis/LLM boundary.

Section 4 combines translation-unit parsing, macro resolution, dataflow,
RMW detection, wrapper inlining, LLVM-IR recovery, functional-state
extraction, and typed transaction extraction under three subsections.

Section 5 combines backend generation and the independent verification gate.
It presents the LLM evidence boundary before backend details, then compilation,
AST receipts, trace oracles, and bounded repair.

Section 6 introduces an explicit setup/RQ subsection, combines compilation and
strict readiness, and combines runtime validation with the DesignWare APB SSI
end-to-end LLM case study.

Section 7 reduces eight short subsections to three: analysis/subsystem
boundaries, verification claims, and scalability/threats to validity. LLM
limitations move here from the verification section.

## Constraints

- Preserve evaluation macros, tables, listings, citations, and labels where
  they remain referenced.
- Do not modify old paper versions.
- Do not reintroduce a standalone Related Work section.
- Keep correctness claims bounded to modeled contracts and checked traces.
- Build with `pdflatex -interaction=nonstopmode -halt-on-error main.tex` twice.
- Require eight main sections and no undefined citations, references, or
  duplicate labels.
