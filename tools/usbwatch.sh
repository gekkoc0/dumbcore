#!/bin/bash
# Log every USB device that appears or disappears (macOS ioreg), with time - to see what the phone shows up as.
# Usage: tools/usbwatch.sh [seconds]      (Spreadtrum boot mode = vendor 0x1782 / 6018, product 0x4d00 / 19712)
end=$(( $(date +%s) + ${1:-1800} ))
snap() { ioreg -p IOUSB -l -w0 | awk -F' = ' '/\+-o /{n=$0; sub(/.*\+-o /,"",n); sub(/  <class.*/,"",n)} /"idVendor" = /{v=$2} /"idProduct" = /{printf "vid %s pid %s  %s\n", v, $2, n}' | sort -u; }
prev=$(snap)
echo "$(date +%T) start; devices now:"; echo "$prev" | sed 's/^/   /'
while [ "$(date +%s)" -lt "$end" ]; do
  cur=$(snap)
  if [ "$cur" != "$prev" ]; then
    diff <(echo "$prev") <(echo "$cur") | grep '^[<>]' | sed "s/^>/$(date +%T) + /; s/^</$(date +%T) - /"
    prev=$cur
  fi
  sleep 0.15
done
