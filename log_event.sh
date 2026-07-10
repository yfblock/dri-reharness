#!/bin/bash
EV="${1:?event}"; DET="${2:-}"
TS=$(date '+%Y-%m-%d %H:%M:%S'); STAMP=$(date '+%Y%m%d-%H%M%S')
LOG=history/timeline.md
[ -f "$LOG" ] || { echo "# reharness 端到端时间线" > "$LOG"; echo >> "$LOG"; }
echo "## [$TS] $EV" >> "$LOG"
[ -n "$DET" ] && echo "$DET" | sed 's/^/  /' >> "$LOG"
echo >> "$LOG"
echo "[$TS] $EV" > "history/${STAMP}.txt"; [ -n "$DET" ] && echo "$DET" >> "history/${STAMP}.txt"
echo "logged: $EV"
