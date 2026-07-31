#!/bin/bash
exec "$(cd "$(dirname "$0")" && pwd)/run_e2e.sh" drivers/test/edu.c pci "$@"
