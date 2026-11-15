#!/bin/bash
# Build spd_dump (github.com/ilyakurdyukov/spreadtrum_flash, public domain) with libusb, plus one small patch
# (tools/spd_dump_brom_retry.patch: repeat the boot ROM "hello" up to 10 times - without it the phone often did not
# answer on macOS / through a USB hub).
#
#   git clone https://github.com/ilyakurdyukov/spreadtrum_flash
#   tools/build_spd_dump.sh spreadtrum_flash          # -> spreadtrum_flash/spd_dump
#
# macOS: brew install libusb.  Linux: apt install libusb-1.0-0-dev (run spd_dump with sudo or add a udev rule).
set -euo pipefail
SRC=${1:?usage: tools/build_spd_dump.sh <spreadtrum_flash folder>}
PATCH="$(cd "$(dirname "$0")" && pwd)/spd_dump_brom_retry.patch"
cd "$SRC"
if ! grep -q "brom checkbaud" spd_dump.c; then patch -p1 < "$PATCH"; fi
if [ "$(uname)" = Darwin ]; then
  P=$(brew --prefix)
  cc -O2 -std=c99 -DUSE_LIBUSB=1 -DLIBUSB_DETACH=0 -I"$P/include" -o spd_dump spd_dump.c -L"$P/lib" -lusb-1.0
else
  cc -O2 -std=c99 -DUSE_LIBUSB=1 -o spd_dump spd_dump.c -lusb-1.0
fi
echo "built: $SRC/spd_dump"
