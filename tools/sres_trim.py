#!/usr/bin/env python3
"""Cut a resource file (sres0001) read from the phone down to its real data: the partition dump is padded with 0xFF
up to the partition size, and an edited file would no longer fit. Official .pac files are already exact.

    python3 -I tools/sres_trim.py <mmi_res from backup> <out.bin>
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sres import Sres

if len(sys.argv) != 3:
    sys.exit(__doc__)
s = Sres(sys.argv[1])
end = max(o + n for _, o, n in s.sections)
tail = s.d[end:]
if tail.count(0xff) != len(tail):
    sys.exit(f'refusing: {len(tail)} bytes after the last section are not all 0xFF')
open(sys.argv[2], 'wb').write(s.d[:end])
print(f'{sys.argv[2]}: {end} bytes (cut {len(tail)} bytes of 0xFF padding)')
