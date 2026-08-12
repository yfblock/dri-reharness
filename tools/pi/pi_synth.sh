#!/bin/bash
# tools/pi/pi_synth.sh - Pi SDK synthesis entry for src/synthesis.py
# 协议:
#   stdin JSON = versioned Pi request envelope; stdout JSON = response envelope.
#   Plain-text stdin remains supported for the historical prompt/C-code interface.
# 退出码: 0 成功; 非0 失败。
#
# 实现: 把 stdin prompt 写临时文件, 调 node tools/synth.mjs, 它用 Pi
# createAgentSession 调 LLM, 把 ```c 代码块写到 out 文件, 这里再 cat 到 stdout。
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"

# project-level config auto-discovery
PI_MODELS_FILE=""
PI_AUTH_FILE=""
if [ -f "$ROOT/.reharness/pi/models.json" ]; then
  PI_MODELS_FILE="$ROOT/.reharness/pi/models.json"
fi
if [ -f "$ROOT/.reharness/pi/auth.json" ]; then
  PI_AUTH_FILE="$ROOT/.reharness/pi/auth.json"
fi

TMP_P="$(mktemp /tmp/pi_synth_prompt.XXXXXX.txt)"
TMP_C="$(mktemp /tmp/pi_synth_out.XXXXXX.c)"
TMP_E="$(mktemp /tmp/pi_synth_err.XXXXXX.txt)"
TMP_O="$(mktemp /tmp/pi_synth_stdout.XXXXXX.txt)"
trap 'rm -f "$TMP_P" "$TMP_C" "$TMP_C.raw" "$TMP_E" "$TMP_O"' EXIT
cat > "$TMP_P"
MODEL="${REHARNESS_LLM_MODEL:-}"          # e.g. ai-alexbd/glm-5.2 ; 空则用配置里第一个可用
TIMEOUT_S="${REHARNESS_LLM_TIMEOUT:-600}"
if [ "$(sed -e '/^[[:space:]]*$/d' "$TMP_P" | head -c 1)" = "{" ]; then
  ARGS=(--request-file "$TMP_P" --timeout "$TIMEOUT_S")
  STRUCTURED=1
else
  ARGS=(--prompt-file "$TMP_P" --out "$TMP_C" --timeout "$TIMEOUT_S")
  STRUCTURED=0
fi
[ -n "$MODEL" ] && ARGS+=(--model "$MODEL")
[ -n "$PI_MODELS_FILE" ] && ARGS+=(--model-file "$PI_MODELS_FILE")
[ -n "$PI_AUTH_FILE" ] && ARGS+=(--auth-file "$PI_AUTH_FILE")

if [ -n "$PI_MODELS_FILE" ]; then
  echo "[pi_synth] project config: $PI_MODELS_FILE" >&2
else
  echo "[pi_synth] fallback to ~/.pi/agent" >&2
fi

if node "$HERE/synth.mjs" "${ARGS[@]}" >"$TMP_O" 2>"$TMP_E"; then
  if [ "$STRUCTURED" -eq 1 ]; then
    cat "$TMP_O"
  else
    cat "$TMP_C"
  fi
  exit 0
else
  echo "pi_synth 失败:" >&2
  cat "$TMP_E" >&2
  if [ "$STRUCTURED" -eq 1 ]; then
    # Preserve a machine-readable failure when the Node process fails early.
    printf '%s\n' '{"protocol_version":1,"ok":false,"error":{"class":"infrastructure","message":"Pi process failed"}}'
  fi
  exit 1
fi
