# C15: coverage-aware callee rescue

## Problem

Multi-source extraction expands direct function summaries for a bounded number
of rounds and then removes helper modules that were called by another target
function.  Reachability alone did not prove that the helper's operations had
actually reached a retained module.  A call chain deeper than the configured
inline depth could therefore lose the deepest helper entirely.

The failure was visible as recognized source MMIO sites with no RIS operation:

- DWC2: 48 sites;
- ASPEED vhub: 4 sites;
- `ahci_dwc`: 6 sites;
- `ahci_sunxi`: 3 sites.

## Direct evidence frontier

The extractor now keeps direct and expanded summaries separately.  A helper is
removed only if retained expanded modules cover every direct register access
owned by that helper.  Coverage identity is `(definition symbol, site_id)`, so
static functions with the same basename in different translation units cannot
cover each other.

When coverage is missing, the extractor retains only the helper's uncovered,
definition-owned register operations.  It never re-emits the helper's expanded
subtree, wrapper-summary descendants, non-register effects or already-covered
sites: doing that on DWC2 can duplicate hundreds of operation occurrences.

The expansion convergence fingerprint also includes `symbol`, `site_id` and
the ordered `inlined_at` evidence chain, preventing convergence before source
identity has propagated.

## Fail-closed claim boundary

This mechanism proves lexical source-site coverage, not complete call
semantics.  It does not prove that every parameterized callsite, caller guard
or dynamic invocation count was instantiated correctly.  Every rescue is
recorded in Formal metadata and produces the blocker:

```text
N helper module(s) retained only for lexical access coverage;
call semantics not proven
```

More importantly, the absence of a rescue is not positive call-context proof:
a shallow call can cover a lexical site while another, deeper parameterized
call to the same helper is truncated.  Until Formal RIS has an explicit
`Call` node and verifier, any helper flattening sets `call_semantics_proven`
to false and blocks backend strict readiness, machine `strict_reliable`,
`whole_program_complete` and `llm_synthesis_ready`.  Missing rescue metadata
also fails closed.

## Results

| Case | Unaccounted before | After | Direct MMIO ops added | Rescued helpers |
|---|---:|---:|---:|---:|
| DWC2 | 48 | 0 | 48 | 21 |
| ASPEED vhub | 4 | 0 | 4 | 1 |
| ahci_dwc | 6 | 0 | 6 | 2 |
| ahci_sunxi | 3 | 0 | 3 | 2 |

DWC2 now contains 3,608 MMIO RIS operations and ASPEED contains 154.  The
three multi-source modules together contain 3,794 MMIO RIS operations.  These
larger counts represent explicit direct evidence frontiers, not a strict-ready
claim.

The regression fixture uses a five-translation-unit chain deeper than the
inline limit.  At depth three, only the direct `leaf` module is rescued and the
single source write is emitted once.  At depth four, the entry module carries
the site and no rescue occurs, but call semantics remain unproven.  A second
fixture combines a shallow and a truncated deep call to the same parameterized
helper: lexical accounting is complete, yet the call-context blocker remains.
Existing shallow helpers remain deduplicated.

The stricter claim boundary intentionally lowers readiness compared with C14:

| Matrix | Harness | Bare-metal | Linux | All backends |
|---|---:|---:|---:|---:|
| 19-driver | 5/19 | 5/19 | 3/19 | 3/19 |
| zero-shot v1 | 7/12 | 7/12 | 6/12 | 6/12 |

All 12 zero-shot cases and all three multi-source drivers still compile in all
three backends.  The first common zero-shot semantic blocker is now
`call_context`, shared by five cases.  This reduction is the removal of an
unsupported positive claim, not a backend compilation regression.

## Next step

The correct call-complete representation is an explicit Formal RIS `Call`
node containing callee identity, arguments, stable callsite ID and guard.  Each
function definition should be emitted once, while entry-root reachability,
SCC/recursion and call-context fanout are verified separately.  This will also
make generated drivers more maintainable than copying expanded helper bodies.
