#!/bin/bash
# reharness LLM 后端: stdin(prompt) -> opencode run -> stdout(patched candidate)
# 通过 REHARNESS_LLM_CMD 调用
MODEL="${REHARNESS_LLM_MODEL:-deepseek/deepseek-v4-flash}"
PROMPT="$(cat)"
# opencode run 接 message 为参数
exec opencode run --model "$MODEL" "$PROMPT"
