#!/bin/bash
# tools/pi_synth.sh — Pi agent core SDK 合成器入口 (供 Python synthesis.py 调用)
# 协议 (与原 REHARNESS_LLM_CMD shell 后端一致):
#   stdin  = 完整 prompt 文本
#   stdout = 合成的 C 代码 (synth.mjs 已提取 ```c 块)
# 退出码: 0 成功; 非0 失败。
#
# 实现: 把 stdin prompt 写临时文件, 调 node tools/synth.mjs, 它用 Pi
# createAgentSession 调 LLM, 把 ```c 代码块写到 out 文件, 这里再 cat 到 stdout。
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
TMP_P="$(mktemp /tmp/pi_synth_prompt.XXXXXX.txt)"
TMP_C="$(mktemp /tmp/pi_synth_out.XXXXXX.c)"
trap 'rm -f "$TMP_P" "$TMP_C" "$TMP_C.raw"' EXIT
cat > "$TMP_P"
MODEL="${REHARNESS_LLM_MODEL:-}"          # e.g. ai-alexbd/glm-5.2 ; 空则用配置里第一个可用
TIMEOUT_S="${REHARNESS_LLM_TIMEOUT:-600}"
ARGS=(--prompt-file "$TMP_P" --out "$TMP_C" --timeout "$TIMEOUT_S")
[ -n "$MODEL" ] && ARGS+=(--model "$MODEL")
if node "$ROOT/tools/synth.mjs" "${ARGS[@]}" >/tmp/pi_synth.stderr 2>&1; then
  cat "$TMP_C"
  exit 0
else
  echo "pi_synth 失败:" >&2
  cat /tmp/pi_synth.stderr >&2
  exit 1
fi
