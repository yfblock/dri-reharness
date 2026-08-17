# Constrained LLM Translation Paper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the v2 paper's opening and Related Work around constrained LLM hybrid translation without claiming that reharness deletes Linux glue from source drivers.

**Architecture:** Preserve the paper's technical system and evaluation. Rewrite only the narrative layer: deterministic source translation, direct LLM translation, and analysis-guided hybrid translation lead to reharness's deterministic-extraction/LLM-expression/deterministic-verification boundary.

**Tech Stack:** LaTeX, ACM `acmart`, BibTeX-style inline bibliography, `pdflatex`, ripgrep.

---

### Task 1: Rewrite Introduction and Motivation

**Files:**
- Modify: `research/paper/v2/sections_1_2.tex`

- [ ] Replace the Introduction with a translation-centered problem statement and the three-family taxonomy.
- [ ] Describe device-core extraction as separation from interleaved Linux glue, never source deletion.
- [ ] Explain that smaller generated targets reduce the hallucination surface but do not prove correctness.
- [ ] Rewrite Motivation around deterministic translation, direct LLM translation, and the deterministic semantic boundary.
- [ ] Preserve supported evaluation macros and contributions.

### Task 2: Reorganize Related Work

**Files:**
- Modify: `research/paper/v2/sections_9_11.tex`

- [ ] Organize Related Work into deterministic rule-based translation, direct LLM translation, and hybrid analysis-guided translation.
- [ ] Position static analysis, formal synthesis, and symbolic execution as foundations for hybrid translation.
- [ ] State the reharness distinction using extraction/separation terminology.
- [ ] Preserve Discussion, Conclusion, and bibliography.

### Task 3: Verify Narrative and Build

**Files:**
- Verify: `research/paper/v2/sections_1_2.tex`
- Verify: `research/paper/v2/sections_9_11.tex`
- Build: `research/paper/v2/main.tex`

- [ ] Search modified sections for claims that reharness removes or deletes source glue.
- [ ] Check section labels and citation keys for consistency.
- [ ] Run `pdflatex -interaction=nonstopmode main.tex` twice from `research/paper/v2/`.
- [ ] Confirm the log contains no undefined citations/references or duplicate labels.
