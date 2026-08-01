#!/usr/bin/env bash
# Compatibility entry point for manifest-driven experiments.
#
# New callers should pass a manifest path directly:
#   ./run.sh e2e path/to/experiment.json [run-experiment options]
#
# The historical source-file form remains supported when a manifest in
# REHARNESS_MANIFEST_DIR (default: benchmarks/experiments) names that source.
# All device facts, commands, limits, and test actions belong to the manifest;
# this wrapper intentionally contains no target-specific policy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$ROOT"

usage() {
  cat >&2 <<'EOF'
Usage: run_e2e.sh <manifest.json> [run-experiment options]
       run_e2e.sh <source.c> [legacy selector] [legacy skip flag]

The source-file form resolves the matching manifest from
REHARNESS_MANIFEST_DIR (default: benchmarks/experiments) and then delegates to
the manifest-driven experiment runner. Legacy positional selectors are
accepted for compatibility but have no effect; target facts must be encoded
in the manifest.
EOF
}

manifest_for_source() {
  local source="$1"
  local manifest_dir="${REHARNESS_MANIFEST_DIR:-$ROOT/benchmarks/experiments}"
  python3 - "$ROOT" "$manifest_dir" "$source" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest_dir = Path(sys.argv[2]).resolve()
source_arg = Path(sys.argv[3])
source = (source_arg if source_arg.is_absolute() else root / source_arg).resolve()

if not manifest_dir.is_dir():
    raise SystemExit(f"manifest directory does not exist: {manifest_dir}")

matches = []
for path in sorted(manifest_dir.rglob("*.json")):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        source_doc = document.get("source", {})
        source_value = source_doc.get("path") if isinstance(source_doc, dict) else None
        if not isinstance(source_value, str):
            continue
        candidate = Path(source_value)
        candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if candidate == source:
            matches.append(path)
    except (OSError, ValueError, json.JSONDecodeError):
        # Unrelated JSON files in the directory are not experiment manifests.
        continue

if len(matches) != 1:
    if not matches:
        raise SystemExit(f"no manifest maps to source: {source}")
    joined = ", ".join(str(item) for item in matches)
    raise SystemExit(f"source maps to multiple manifests: {joined}")
print(matches[0])
PY
}

[[ $# -gt 0 ]] || { usage; exit 2; }

first="$1"
shift
manifest=""

# A manifest is the canonical interface.  Accept any existing JSON path so
# callers are not forced to use a particular filename convention.
if [[ -f "$first" ]] && [[ "$(basename "$first")" == *.json ]]; then
  manifest="$first"
else
  manifest="$(manifest_for_source "$first")"

  # The former interface accepted up to two positional policy selectors after
  # the source. They are deliberately ignored: the manifest is authoritative.
  # Stop at the first option so run_experiment options (for example --output)
  # retain their original meaning.
  legacy_count=0
  while [[ $# -gt 0 && "$1" != --* ]]; do
    legacy_count=$((legacy_count + 1))
    shift
  done
  if [[ "$legacy_count" -gt 2 ]]; then
    echo "too many legacy positional arguments; pass a manifest and options" >&2
    exit 2
  fi
fi

if [[ ! -f "$manifest" ]]; then
  echo "manifest not found: $manifest" >&2
  exit 2
fi

exec "$ROOT/run.sh" experiment "$manifest" "$@"
