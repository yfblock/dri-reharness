#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$ROOT"
EV="${1:?event}"; DET="${2:-}"
TS=$(date '+%Y-%m-%d %H:%M:%S'); STAMP=$(date '+%Y%m%d-%H%M%S')
LOG="$ROOT/research/history/timeline.md"
[ -f "$LOG" ] || { echo "# reharness 端到端时间线" > "$LOG"; echo >> "$LOG"; }
echo "## [$TS] $EV" >> "$LOG"
[ -n "$DET" ] && echo "$DET" | sed 's/^/  /' >> "$LOG"
echo >> "$LOG"
ENTRY="$ROOT/research/history/${STAMP}.txt"
echo "[$TS] $EV" > "$ENTRY"; [ -n "$DET" ] && echo "$DET" >> "$ENTRY"
echo "logged: $EV"
