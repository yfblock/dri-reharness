# External-call annotations (RIS 0.3.0)

`data/external-call-annotations.json` is the reviewed store of external-call
semantics. It is **data, not code**: version it, diff it, review it like a
patch. The extractor never calls a model — it only merges this file at
formization time (`formalize._attach_external_call_nodes`).

## Resolution order (fail-closed)

1. **Reviewed annotation** — entry in the store wins (grounded kernel-source
   analysis or deliberate human correction).
2. **Deterministic rule table** — `src/extractor/external_semantics.py`
   `_RULES`, kernel naming conventions only. Confidence 0.7.
3. **`unknown`** — visible first-class ExternalCall node, never dropped.

## Schema

```json
{
  "<callee name>": {
    "category": "alloc",            // required, from EXTERNAL_CATEGORIES
    "confidence": 0.9,              // required for model entries
    "source": "kernel-tree",        // rule | kernel-tree | model
    "return": "void * or NULL on failure",
    "effects": ["allocates size bytes", "device-managed lifetime"],
    "params": {"size": "byte count", "gfp": "allocation flags"},
    "porting_hint": "map to the target allocator; check NULL",
    "basis": "include/linux/slab.h: kmalloc's doc block"  // grounding
  }
}
```

Closed category enum (`external_semantics.EXTERNAL_CATEGORIES`):
`pure, delay, alloc, free, lock, unlock, dma-map, dma-sync, dma-unmap,
power-on, power-off, reset, register-access, print, probe-defer, unknown`.
Adding a member is a schema change.

## Workflow

```
tools/annotate_external_calls.py scan   # census over corpus → draft JSON
tools/annotate_external_calls.py apply  # vendor/linux source → LLM, closed
                                        # category only, grounded by body
human review of the diff                # annotations.json is reviewable
git add data/external-call-annotations.json
```

Rules cover the unambiguous naming families (~50-70% of corpus externals);
the annotator drafts the rest with `basis` citing the kernel tree; humans
accept/reject; extraction stays deterministic and offline-safe (missing
store degrades every unlisted name to `unknown`, nothing else changes).
