# v2 Paper Revision Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revise the v2 paper so its claims match the current artifacts and its remaining system experiments are explicit.

**Architecture:** Three file-owned edits run in parallel: technical contract/verification claims, evaluation and experiment debt, and references/limitations/formatting. The root agent then reconciles shared terminology and runs the paper build. A fresh review pass follows integration.

**Tech Stack:** LaTeX/acmart, repository experiment artifacts, `pdflatex`, `pdftotext`, `rg`.

---

### Task 1: Technical contract and verification claims

**Files:**
- Modify: `research/paper/v2/sections_3_5.tex`
- Modify: `research/paper/v2/sections_6_8.tex` (verification paragraphs only)

- [ ] Replace unsupported “denotational semantics” wording with evidence-IR wording unless a concrete semantic definition exists in the cited artifact.
- [ ] Align AST/IR merge, receipt digest, branch matching, and extra-access claims with current verifier behavior.
- [ ] Preserve the measured numbers and add precise non-guarantees.

### Task 2: Evaluation framing and experiment debt

**Files:**
- Modify: `research/paper/v2/sections_6_8.tex` (evaluation paragraphs and new debt subsection)
- Modify: `research/paper/v2/sections_1_2.tex` (contribution/evaluation wording if needed)
- Create: `research/paper/v2/EXPERIMENT_DEBT.md`

- [ ] Separate deterministic emitter results from the single LLM DesignWare artifact case.
- [ ] Rename or qualify synthesis-eligibility metrics so they are not mistaken for LLM pass rates.
- [ ] Add a concise experiment-debt table covering extraction ground truth, extra-access/guard mutation testing, repeated LLM trials, baselines/ablations, Rust verification, and multi-source semantic validation.
- [ ] Keep all existing generated result values unchanged.

### Task 3: References, limitations, and metadata

**Files:**
- Modify: `research/paper/v2/sections_9_11.tex`
- Modify: `research/paper/v2/main.tex`

- [ ] Correct or remove unverifiable bibliography entries.
- [ ] Rewrite conclusion and limitations to avoid claiming general semantic authority or full footprint recovery.
- [ ] Fix submission placeholders only where the v2 source can do so without inventing venue metadata.

### Task 4: Integration and verification

**Files:** all modified v2 files

- [ ] Run `pdflatex` twice from `research/paper/v2/` using the existing generated-results input.
- [ ] Check the log for undefined citations/references and inspect overfull/underfull warnings.
- [ ] Run an independent whole-paper review against the acceptance criteria.
- [ ] Record any unresolved system experiment debt in the final report.
