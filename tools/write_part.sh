#!/bin/bash
# WRITE one partition of a Nokia 3210 4G (UMS9117) over USB, then read it back and compare. This changes the phone.
#
#   tools/write_part.sh <partition id> <file>          e.g. 0x90000003 work/mod_test/.../nv_running.bin
#
# Allowed ids (anything else is refused): 0x90000003 running NV (VNTS), 0x90000004 resources (mmi_res).
# The code images (boot/kernel/user), the fixed NV with IMEI/calibration (0x90000001/0x9000000f) and PhaseCheck are
# never written by this script. Rollback = the same command with the file from your backup.
# Needs SPD (spd_dump with tools/spd_dump_brom_retry.patch) and FDL_DIR (fdl1.bin, fdl2.bin from an official .pac).
# Before plugging in: phone OFF, cable OUT; then hold '*' and plug the cable in when asked.
set -euo pipefail
cd "$(dirname "$0")/.."
ID=${1:?usage: tools/write_part.sh <partition id> <file>}
FILE=${2:?usage: tools/write_part.sh <partition id> <file>}
SPD=${SPD:-work/build/spd_dump}
FW=${FDL_DIR:-work/ext/official_3210_11.00.17.00_QB_16ICN18HK00}
case "$ID" in
  0x90000003) KIND="running NV"; MAGIC=VNTS ;;
  0x90000004) KIND="resources (mmi_res)"; MAGIC=sres0001 ;;
  *) echo "refusing: $ID is not on the allowed list (0x90000003, 0x90000004)"; exit 1 ;;
esac
[ -x "$SPD" ] || { echo "spd_dump not found ($SPD)"; exit 1; }
[ -f "$FW/fdl1.bin" ] && [ -f "$FW/fdl2.bin" ] || { echo "fdl1.bin/fdl2.bin not found in $FW"; exit 1; }
[ -f "$FILE" ] || { echo "no file $FILE"; exit 1; }
head -c ${#MAGIC} "$FILE" | grep -q "^$MAGIC" || { echo "$FILE does not start with $MAGIC - not a $KIND image"; exit 1; }
SIZE=$(stat -f %z "$FILE" 2>/dev/null || stat -c %s "$FILE")
SUM=$(shasum -a 256 "$FILE" | cut -c1-64)
echo "About to WRITE $KIND ($ID): $FILE, $SIZE bytes, sha256 $SUM"
read -r -p "Type WRITE to continue: " ans
[ "$ans" = WRITE ] || { echo "cancelled"; exit 1; }
OUT=${OUT_ROOT:-backup}/$(date +%Y-%m-%d_%H%M)_write_${ID}
mkdir -p "$OUT"
cp "$FILE" "$OUT/written.bin"

args=(--wait ${WAIT:-600} verbose 1 timeout 30000 keep_charge 1
      fdl "$FW/fdl1.bin" 0x6200
      blk_size 0x1000
      fdl "$FW/fdl2.bin" 0x80100000
      write_data "$ID" 0 "$SIZE" "$FILE"
      read_flash "$ID" 0 "$SIZE" "$OUT/readback.bin"
      power_off)
echo ">>> Phone OFF, hold '*' and plug in the USB cable now..."
"$SPD" "${args[@]}" 2>&1 | tee "$OUT/spd_dump.log"
echo
if cmp -s "$FILE" "$OUT/readback.bin"; then
  echo "OK: read-back matches the written file ($OUT). Unplug the cable, then switch the phone on."
else
  echo "!!! read-back differs or is missing - do NOT switch the phone on yet; see $OUT/spd_dump.log"
  exit 2
fi
