# V2 Academic Figures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three compact, academic TikZ figures to the v2 paper that visualize compilation/readiness, the bounded verification scope, and multi-source MMIO evidence while preserving generated-data provenance.

**Architecture:** Keep all graphics in the existing section files and reuse the TikZ/xcolor setup from `main.tex`. Scalar values for the readiness chart come from existing generated macros; per-module multi-source values are emitted by `tools/reporting/generate_paper_results.py` into `generated_results.tex`, so the chart and table share the experiment JSON source. Captions and adjacent prose explicitly constrain what each figure establishes.

**Tech Stack:** LaTeX `acmart`, TikZ, `xcolor`, Python result-macro generator, sequential `pdflatex`.

---

### Task 1: Emit per-module multi-source chart macros

**Files:**
- Modify: `tools/reporting/generate_paper_results.py:43-89`
- Regenerate: `research/paper/v2/generated_results.tex`

- [ ] **Step 1: Add deterministic macro names for each multi-source row**

Extend the existing `macros` construction after the aggregate multi-source fields. For each `multi_rows` entry, derive a stable CamelCase suffix (`AspeedVhub`, `C67x00`, `Dwc2`) and emit source/RIS counts from the same row fields used by `MultiSourceResultsTable`:

```python
    multi_macro_rows = {
        "AspeedVhub": next(r for r in multi_rows if r["driver"] == "aspeed-vhub"),
        "C67x00": next(r for r in multi_rows if r["driver"] == "c67x00"),
        "Dwc2": next(r for r in multi_rows if r["driver"] == "dwc2"),
    }
    for suffix, row in multi_macro_rows.items():
        macros[f"MultiSource{suffix}SourceMMIO"] = row.get(
            "source_mmio_primitives", {}).get("total", 0)
        macros[f"MultiSource{suffix}RISMMIO"] = row.get("ris_mmio_ops", 0)
```

Place this before the loop that appends `\newcommand` lines so all six macros are emitted. Keep the explicit driver names because the three modules are part of the frozen evaluation manifest; fail loudly if one is missing rather than silently emitting zero.

- [ ] **Step 2: Regenerate and inspect the output**

Run:

```bash
python3 tools/reporting/generate_paper_results.py
rg -n "MultiSource(AspeedVhub|C67x00|Dwc2)(Source|RIS)MMIO" research/paper/v2/generated_results.tex
```

Expected output contains `101`, `154`, `2`, `32`, `804`, and `3608` in the corresponding macros, with no unrelated generated changes.

### Task 2: Add the compilation/readiness gap figure

**Files:**
- Modify: `research/paper/v2/sections_6_8.tex:269-290`

- [ ] **Step 1: Insert the figure after the strict-readiness explanatory paragraph**

Add a one-column `figure` using a `tikzpicture` and `\pgfmathsetmacro` values sourced from `\HarnessCompileCount`, `\BaremetalCompileCount`, `\LinuxCompileCount`, `\HarnessReadyCount`, `\BaremetalReadyCount`, `\LinuxReadyCount`, and `\EvalDrivers`. Draw paired blue/orange bars for each backend, y ticks at 0/5/10/15/19, a compact legend, and a “drivers (of 19)” y-axis label. Use `\resizebox{\columnwidth}{!}{%` around the TikZ picture and close it with `}` before the caption so the caption remains readable.

```latex
\begin{figure}[t]
\centering
\resizebox{\columnwidth}{!}{%
\begin{tikzpicture}[x=1.05cm,y=0.16cm,font=\footnotesize]
  \pgfmathsetmacro{\maxdrivers}{\EvalDrivers}
  \draw[->] (0,0) -- (0,\maxdrivers+1) node[above] {drivers};
  \draw[->] (0,0) -- (4.6,0);
  \foreach \y in {0,5,10,15,19} {
    \draw[gray!45] (0,\y) -- (4.6,\y);
    \node[left] at (0,\y) {\y};
  }
  \pgfmathsetmacro{\hc}{\HarnessCompileCount}
  \pgfmathsetmacro{\hr}{\HarnessReadyCount}
  \pgfmathsetmacro{\bc}{\BaremetalCompileCount}
  \pgfmathsetmacro{\br}{\BaremetalReadyCount}
  \pgfmathsetmacro{\lc}{\LinuxCompileCount}
  \pgfmathsetmacro{\lr}{\LinuxReadyCount}
  \fill[blue!80!black] (0.55,0) rectangle (0.85,\hc);
  \fill[orange!85!black] (0.90,0) rectangle (1.20,\hr);
  \fill[blue!80!black] (1.85,0) rectangle (2.15,\bc);
  \fill[orange!85!black] (2.20,0) rectangle (2.50,\br);
  \fill[blue!80!black] (3.15,0) rectangle (3.45,\lc);
  \fill[orange!85!black] (3.50,0) rectangle (3.80,\lr);
  \node[below] at (0.875,0) {Harness};
  \node[below] at (2.175,0) {Bare-metal};
  \node[below] at (3.475,0) {Linux};
  \fill[blue!80!black] (4.05,16.8) rectangle (4.25,18.0);
  \node[right] at (4.28,17.4) {compilation};
  \fill[orange!85!black] (4.05,15.2) rectangle (4.25,16.4);
  \node[right] at (4.28,15.8) {strict ready};
\end{tikzpicture}%
}
\caption{Compilation versus strict artifact readiness across the 19-driver evaluation. Blue bars count compilable deterministic outputs; orange bars count artifacts passing the modeled strict gate. Compilation is necessary but not sufficient, and neither bar establishes whole-driver equivalence.}
\Description{Grouped blue and orange bars compare compilation and strict readiness for harness, bare-metal, and Linux backends.}
\label{fig:readiness-gap}
\end{figure}
```

- [ ] **Step 2: Add one cross-reference sentence**

Append to the paragraph immediately before the figure: `Figure~\ref{fig:readiness-gap} makes the compilation/readiness separation explicit.` Do not repeat numerical values outside generated macros.

### Task 3: Add the verification scope matrix

**Files:**
- Modify: `research/paper/v2/sections_6_8.tex:63-156`

- [ ] **Step 1: Insert a bounded-scope TikZ matrix near the verification-gate description**

Create a one-column figure with a dashed outer boundary labelled `bounded evidence contract`. The left panel is a vertical sequence of four blue/orange check nodes connected by arrows: `Compilation`, `Receipt accounting`, `AST primitive-shape + callback attestation`, and `Exercised-path trace`. The right panel is gray and headed `Not established by this gate`, with five short limitation rows. Add an orange warning footer reading `does not establish whole-driver equivalence`.

```latex
\begin{figure}[t]
\centering
\resizebox{\columnwidth}{!}{%
\begin{tikzpicture}[font=\scriptsize, node distance=0.22cm and 0.34cm]
  \node[draw,dashed,rounded corners,inner sep=5pt,fit={(0,0) (8.0,5.2)},label={[font=\scriptsize]above:bounded evidence contract}] (boundary) {};
  \node[draw,fill=blue!10,minimum width=2.55cm,minimum height=0.45cm,align=center] (c1) at (1.45,4.45) {Compilation};
  \node[draw,fill=orange!15,minimum width=2.55cm,minimum height=0.45cm,align=center] (c2) at (1.45,3.45) {Receipt accounting};
  \node[draw,fill=blue!10,minimum width=2.55cm,minimum height=0.45cm,align=center] (c3) at (1.45,2.45) {AST shape + callback};
  \node[draw,fill=orange!15,minimum width=2.55cm,minimum height=0.45cm,align=center] (c4) at (1.45,1.45) {Exercised trace};
  \draw[->,thick] (c1) -- (c2);
  \draw[->,thick] (c2) -- (c3);
  \draw[->,thick] (c3) -- (c4);
  \node[draw,fill=gray!12,minimum width=4.15cm,minimum height=3.65cm,align=left,anchor=north west] (outside) at (3.4,4.75) {\textbf{Not established by this gate}\\[2pt]$\bullet$ arbitrary addresses/values\\$\bullet$ guard equivalence for every input\\$\bullet$ unexercised global order\\$\bullet$ extra accesses and side effects\\$\bullet$ DMA/IRQ/lifecycle behavior};
  \node[draw=orange!85!black,fill=orange!8,minimum width=7.25cm,minimum height=0.42cm,align=center] at (4.0,0.35) {does not establish whole-driver equivalence};
\end{tikzpicture}%
}
\caption{Scope of the verification gate. The left column lists checks implemented by the artifact; the right column records properties intentionally outside the gate. The figure describes bounded evidence checks, not complete verification.}
\Description{A bounded evidence contract encloses a four-stage verification flow and a separate panel of properties not established by the gate.}
\label{fig:verification-scope}
\end{figure}
```

- [ ] **Step 2: Reference the figure in the surrounding prose**

After the paragraph that introduces compilation, receipt accounting, primitive-shape checks, and exercised traces, add `The boundary and its explicit non-claims are summarized in Figure~\ref{fig:verification-scope}.` Keep the existing limitation paragraph unchanged apart from this reference.

### Task 4: Add the multi-source MMIO evidence chart

**Files:**
- Modify: `research/paper/v2/sections_6_8.tex:318-328`

- [ ] **Step 1: Insert a log-scale grouped bar chart after the multi-source table**

Use the six generated per-module macros from Task 1. Draw paired blue/orange bars for aspeed-vhub, c67x00, and dwc2 with a logarithmic y coordinate (e.g., `\pgfmathparse{ln(value)/ln(10)}`), major ticks labelled 1, 10, 100, and 1000, and a legend. Keep the 2-to-32 c67x00 pair visible and use a caption that distinguishes evidence propagation from precision/recall and complete footprint claims.

```latex
\begin{figure}[t]
\centering
\resizebox{\columnwidth}{!}{%
\begin{tikzpicture}[x=1.45cm,y=1.0cm,font=\footnotesize]
  \draw[->] (0,0) -- (0,3.75) node[above] {MMIO operations (log$_{10}$)};
  \draw[->] (0,0) -- (4.55,0);
  \foreach \y/\label in {0/1,1/10,2/100,3/1000} {
    \draw[gray!45] (0,\y) -- (4.55,\y);
    \node[left] at (0,\y) {\label};
  }
  \pgfmathsetmacro{\asrc}{\MultiSourceAspeedVhubSourceMMIO}
  \pgfmathsetmacro{\aris}{\MultiSourceAspeedVhubRISMMIO}
  \pgfmathsetmacro{\csrc}{\MultiSourceC67x00SourceMMIO}
  \pgfmathsetmacro{\cris}{\MultiSourceC67x00RISMMIO}
  \pgfmathsetmacro{\dsrc}{\MultiSourceDwc2SourceMMIO}
  \pgfmathsetmacro{\dris}{\MultiSourceDwc2RISMMIO}
  \pgfmathsetmacro{\asrclog}{ln(\asrc)/ln(10)}
  \pgfmathsetmacro{\arislog}{ln(\aris)/ln(10)}
  \pgfmathsetmacro{\csrclog}{ln(\csrc)/ln(10)}
  \pgfmathsetmacro{\crislog}{ln(\cris)/ln(10)}
  \pgfmathsetmacro{\dsrclog}{ln(\dsrc)/ln(10)}
  \pgfmathsetmacro{\drislog}{ln(\dris)/ln(10)}
  \fill[blue!80!black] (0.55,0) rectangle (0.85,\asrclog);
  \fill[orange!85!black] (0.90,0) rectangle (1.20,\arislog);
  \fill[blue!80!black] (1.85,0) rectangle (2.15,\csrclog);
  \fill[orange!85!black] (2.20,0) rectangle (2.50,\crislog);
  \fill[blue!80!black] (3.15,0) rectangle (3.45,\dsrclog);
  \fill[orange!85!black] (3.50,0) rectangle (3.80,\drislog);
  \node[below] at (0.875,0) {aspeed-vhub};
  \node[below] at (2.175,0) {c67x00};
  \node[below] at (3.475,0) {dwc2};
  \fill[blue!80!black] (4.00,2.95) rectangle (4.20,3.15);
  \node[right] at (4.23,3.05) {source MMIO};
  \fill[orange!85!black] (4.00,2.55) rectangle (4.20,2.75);
  \node[right] at (4.23,2.65) {RIS MMIO};
\end{tikzpicture}%
}
\caption{Source MMIO primitives and propagated RIS MMIO operations for the three multi-source modules (log scale). Counts show recorded evidence after propagation; they are not precision/recall measurements and do not establish a complete hardware-access footprint.}
\Description{Log-scale grouped bars compare source MMIO and propagated RIS MMIO counts for aspeed-vhub, c67x00, and dwc2.}
\label{fig:multisource-mmio}
\end{figure}
```

- [ ] **Step 2: Add a cross-reference without duplicating counts**

In the paragraph beginning `MMIO propagation expands`, append `Figure~\ref{fig:multisource-mmio} shows the per-module distribution on a logarithmic scale.`

### Task 5: Build and inspect the paper

**Files:**
- Verify: `research/paper/v2/main.tex`, `research/paper/v2/main.pdf`, `research/paper/v2/main.log`

- [ ] **Step 1: Run the generator and sequential LaTeX builds**

Run from the paper directory (never in parallel):

```bash
cd research/paper/v2
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex
```

Expected: exit status 0, all three new figure references resolved, and no `Undefined control sequence` errors.

- [ ] **Step 2: Run repository hygiene checks**

```bash
cd ../..
git diff --check
rg -n "undefined|Undefined|multiply defined" research/paper/v2/main.log || true
pdfinfo research/paper/v2/main.pdf | rg "Pages"
```

Expected: `git diff --check` is silent, no undefined-reference diagnostics, and a finite page count with the figures present. If an overfull box is introduced, adjust only figure dimensions/font sizes and rebuild sequentially.

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --stat
git diff -- research/paper/v2/sections_6_8.tex tools/reporting/generate_paper_results.py research/paper/v2/generated_results.tex
```

Confirm that changes are limited to the three figures, their references/captions, and generated macros; preserve unrelated dirty-worktree edits.
