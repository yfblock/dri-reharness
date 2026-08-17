# Conference Paper Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the v2 paper into the approved eight-section conference-paper structure.

**Architecture:** Preserve the paper's evidence and experimental content while merging related conceptual stages. The resulting narrative moves from problem and motivation, through evidence-contract construction and extraction, to constrained translation/verification and evaluation.

**Tech Stack:** LaTeX, ACM `acmart`, `pdflatex`, ripgrep.

---

### Task 1: Compress Motivation and Remove Related Work

**Files:**
- Modify: `research/paper/v2/sections_1_2.tex`
- Modify: `research/paper/v2/sections_9_11.tex`

- [ ] Merge the four Motivation subsections into two focused subsections.
- [ ] Preserve the cited three-way translation comparison in Introduction and Motivation.
- [ ] Remove the standalone Related Work section while retaining its bibliography entries.

### Task 2: Merge System Design and Evidence Contract

**Files:**
- Modify: `research/paper/v2/sections_3_5.tex`

- [ ] Merge System Overview and Formal RIS into `System Design and Evidence Contract`.
- [ ] Add explicit subsections for architecture, RIS, device/function semantics, and backend bindings/evidence JSON.
- [ ] Rename and compress extraction into `Device-Core Contract Extraction` with three subsections.

### Task 3: Merge Translation and Verification

**Files:**
- Modify: `research/paper/v2/sections_6_8.tex`

- [ ] Merge generation and verification into `Constrained LLM Translation and Verification`.
- [ ] Organize it into backend adapters, evidence-constrained translation, deterministic checks, and bounded repair.
- [ ] Move limitations prose into Discussion.

### Task 4: Focus Evaluation and Discussion

**Files:**
- Modify: `research/paper/v2/sections_6_8.tex`
- Modify: `research/paper/v2/sections_9_11.tex`

- [ ] Add `Experimental Setup and Research Questions`.
- [ ] Consolidate evaluation into extraction quality, translation/readiness, scaling, and end-to-end validation.
- [ ] Consolidate Discussion into three subsections and keep Conclusion independent.

### Task 5: Verify the Conference Structure

**Files:**
- Verify: `research/paper/v2/*.tex`
- Build: `research/paper/v2/main.tex`

- [ ] Confirm exactly eight main `\\section` declarations and no Related Work section.
- [ ] Check references, labels, and citation keys.
- [ ] Compile twice with `pdflatex -interaction=nonstopmode -halt-on-error main.tex`.
- [ ] Confirm no undefined citations/references or duplicate labels in `main.log`.
