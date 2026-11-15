#!/bin/bash
# Import a MOCOR code image into the project's Ghidra repo, seed Thumb functions, auto-analyse, export.
# Usage: tools/ghidra_analyze.sh <image.bin> <base> <name>   e.g. ... EXEC_USER_IMAGE.bin 0x88000000 user
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG="$1"; BASE="$2"; NAME="$3"
export JAVA_HOME=/opt/homebrew/opt/openjdk@25
GH="$ROOT/work/tools/ghidra/support/analyzeHeadless"
OUT="$ROOT/work/ghidra"
mkdir -p "$OUT/proj"
python3 -I "$ROOT/tools/seeds.py" "$IMG" "$BASE" "$OUT/${NAME}_seeds.txt"
"$GH" "$OUT/proj" mocor -overwrite \
  -import "$IMG" -loader BinaryLoader -loader-baseAddr "$BASE" -loader-fileOffset 0x200 \
  -processor ARM:LE:32:v7 -cspec default \
  -scriptPath "$ROOT/tools/ghidra_scripts" \
  -preScript SeedThumb.java "$OUT/${NAME}_seeds.txt" \
  -postScript ExportFuncs.java "$OUT/${NAME}_funcs.jsonl" \
  -analysisTimeoutPerFile 14400 -max-cpu 6 \
  > "$OUT/${NAME}_analyze.log" 2>&1
echo "done: $OUT/${NAME}_funcs.jsonl"
