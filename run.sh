#!/usr/bin/env bash
# 兼容转发: 逻辑全部在 qa/verification/reharness_cli.py
exec "${PYTHON:-python3}" "$(dirname "${BASH_SOURCE[0]}")/qa/verification/reharness_cli.py" "$@"
