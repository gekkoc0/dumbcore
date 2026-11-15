#!/bin/bash
# Read-only backup of a Nokia 3210 4G (2024, UMS9117) over USB from a Mac, with spd_dump + the phone's own FDLs.
#
#   tools/dump_phone.sh test     # ~1 min: connect, load FDL1/FDL2, read NV, PhaseCheck, boot0 - proves the chain works
#   tools/dump_phone.sh full     # everything: boot, kernel, user, resources, DSP, all NV, file system, ...
#   tools/dump_phone.sh scan     # 4 KB from every other id 0x80000000-0f, 0x90000000-2f: finds partitions missing from the .pac
#   tools/dump_phone.sh extra    # re-read running NV and hidden disk C: in full (larger than the caps of 'full')
#   tools/dump_phone.sh hidden   # read the ids found by 'scan' (NV copy and three small areas)
#
# Needs: SPD = path to spd_dump (build: tools/build_spd_dump.sh), FDL_DIR = folder with fdl1.bin and fdl2.bin taken from
# any official .pac of this phone (tools/extract_all.py unpacks a .pac; the FDLs are the same in all known builds).
#   SPD=~/spreadtrum_flash/spd_dump FDL_DIR=~/fw/unpacked tools/dump_phone.sh test
# Output goes to backup/<date>_<mode>/ in the project folder (OUT_ROOT=... to change).
#
# Then: phone OFF, hold '*' and plug the USB cable in. Keep holding '*' until the log says the FDL is loaded.
# ONLY read commands are used here (read_flash, power_off). Nothing is written, erased or repartitioned.
# The dump contains your IMEI and calibration - it is private: keep it local, never upload it anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${1:-test}
SPD=${SPD:-work/build/spd_dump}
FW=${FDL_DIR:-work/ext/official_3210_11.00.17.00_QB_16ICN18HK00}
[ -x "$SPD" ] || { echo "spd_dump not found ($SPD): build it with tools/build_spd_dump.sh and set SPD=..."; exit 1; }
[ -f "$FW/fdl1.bin" ] && [ -f "$FW/fdl2.bin" ] || { echo "fdl1.bin/fdl2.bin not found in $FW: set FDL_DIR=... (see docs/backup.md)"; exit 1; }
OUT=${OUT_ROOT:-backup}/$(date +%Y-%m-%d_%H%M)_$MODE
mkdir -p "$OUT"

BIG=0x8000000          # size cap for partitions without a header: read_flash stops at the partition end by itself
args=(--wait ${WAIT:-600} verbose ${VERB:-1} timeout 3000 keep_charge 1
      fdl "$FW/fdl1.bin" 0x6200
      blk_size 0x1000
      fdl "$FW/fdl2.bin" 0x80100000)
rd() { args+=(read_flash "$1" 0 "$2" "$OUT/$3"); }     # id, size|auto, file name

if [ "$MODE" = hidden ]; then                # ids found by 'scan' that are not in the .pac
  rd 0x9000000f 0x100000 nv_copy_0f.bin        # starts like the fixed NV: backup copy?
  rd 0x90000020 0x400000 area_20.bin           # zeros at the start
  rd 0x9000001c 0x400000 area_1c.bin           # 0xFF at the start
  rd 0x90000022 0x400000 area_22.bin           # 0xFF at the start
elif [ "$MODE" = scan ]; then                  # probe every id around the known ones: 4 KB each, to find partitions not in the .pac
  known=" 80000001 80000002 80000003 80000004 80000008 90000001 90000002 90000003 90000004 90000005 90000006 90000007 90000013 90000018 90000019 9000001a 9000001b 9000001d "
  for base in 0x80000000 0x90000000; do
    for i in $(seq ${SCAN_FROM:-0} 47); do
      [ $base = 0x80000000 ] && [ $i -gt 15 ] && continue
      id=$(printf '%08x' $((base + i)))
      case "$known" in *" $id "*) continue;; esac
      rd 0x$id 0x1000 scan_$id.bin
    done
  done
elif [ "$MODE" = extra ]; then                 # second pass for areas larger than the first caps
  rd 0x90000003 auto     nv_running.bin        # VNTS header gives the size (5040 x 0x400)
  rd 0x90000007 0x800000 hidden_disk.bin       # FAT12, 7056 x 1024 bytes
elif [ "$MODE" = test ]; then
  rd 0x90000001 $BIG  nv_fixed.bin
  rd 0x90000002 $BIG  phasecheck.bin
  rd 0x80000001 auto  boot0.bin
else
  # Each id is a large window in FDL2 (NV: ~110 MB, almost all 0xFF), and reading past its end kills the session.
  # So: caps a bit above the stock sizes (.pac), and the unknown / biggest area (phone memory) goes last.
  rd 0x80000001 auto     boot0.bin
  rd 0x80000002 auto     boot1.bin
  rd 0x80000003 auto     kernel.bin
  rd 0x80000004 auto     user.bin
  rd 0x90000001 0x100000 nv_fixed.bin          # NV: calibration, IMEI (stock image 0xb0ba8)
  rd 0x90000002 0x100000 phasecheck.bin        # production phases, serial
  rd 0x90000003 0x400000 nv_running.bin        # running NV
  rd 0x9000001a 0x400000 nv_user.bin           # user NV (settings)
  rd 0x90000004 0x2000000 mmi_res.bin          # resources (stock 0x11be610)
  rd 0x90000005 0x400000 dsp_05.bin            # DSP (stock 0x288000 / 0x300000)
  rd 0x90000006 0x400000 dsp_06.bin
  rd 0x90000012 0x400000 dsp_12.bin
  rd 0x90000013 0x100000 cm4.bin               # stock 0xd8cc
  rd 0x90000018 0x100000 cm4_ab.bin            # stock 0x7126c
  rd 0x90000014 0x100000 wifi.bin
  rd 0x90000019 0x100000 deltanv.bin
  rd 0x9000001b 0x200000 apn.bin               # stock 0x840b6
  rd 0x9000001d 0x100000 ims_toggle.bin
  rd 0x90000007 0x400000 hidden_disk.bin
  rd 0x90000008 0x400000 fota.bin
  rd 0x9000000a 0x400000 du.bin
  rd 0x9000000e 0x400000 romdisk.bin
  rd 0x90000016 0x100000 xfile.bin
  rd 0x90000017 0x100000 autosms.bin
  rd 0x80000008 0x5000000 filesystem.bin       # phone memory (D:), last: size unknown, may end the session
fi
args+=(power_off)

echo "Output: $OUT"
echo ">>> Phone OFF, hold '*' and plug in the USB cable now (waiting up to 10 min)..."
"$SPD" "${args[@]}" 2>&1 | tee "$OUT/spd_dump.log"
echo
echo "Files:"; ls -l "$OUT"
( cd "$OUT" && shasum -a 256 *.bin > SHA256SUMS ) && echo "checksums -> $OUT/SHA256SUMS"
