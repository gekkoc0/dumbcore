#!/bin/bash
# Decompile functions from the analysed Ghidra project.
# Usage: tools/decompile.sh kernel|user <hexaddr> [<hexaddr> ...]   -> work/ghidra/c/<image>/<addr>.c
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "$1" in
  kernel) PROG=EXEC_KERNEL_IMAGE.bin ;;
  user)   PROG=EXEC_USER_IMAGE.bin ;;
  *) echo "kernel|user"; exit 1 ;;
esac
WHICH="$1"; shift
export JAVA_HOME=/opt/homebrew/opt/openjdk@25
OUT="$ROOT/work/ghidra/c/$WHICH"
"$ROOT/work/tools/ghidra/support/analyzeHeadless" "$ROOT/work/ghidra/proj" mocor \
  -process "$PROG" -noanalysis -readOnly \
  -scriptPath "$ROOT/tools/ghidra_scripts" -postScript Decompile.java "$OUT" "$@" 2>&1 \
  | grep -E 'decompiled|no function|ERROR' || true
