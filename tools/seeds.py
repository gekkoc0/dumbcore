#!/usr/bin/env python3
"""Find likely Thumb function entry points in a raw code image (for seeding Ghidra).

A seed = address that (a) starts with PUSH {..., lr} and (b) is the target of a Thumb BL/BLX
or of a Thumb function pointer (odd word) somewhere in the image.
Usage: seeds.py image.bin base out.txt   (DHTB header of 0x200 bytes is skipped)
"""
import struct, sys
from array import array

path, base, out = sys.argv[1], int(sys.argv[2], 0), sys.argv[3]
d = open(path, 'rb').read()[0x200:]
n = len(d)
hw = array('H', d[:n & ~1])


def is_push(o):
    if o + 4 > n:
        return False
    h = hw[o >> 1]
    if h & 0xff00 == 0xb500:
        return True
    return h == 0xe92d and hw[(o >> 1) + 1] & 0x4000 and not hw[(o >> 1) + 1] & 0xa000


targets = set()
# Thumb BL / BLX (32-bit): first half 11110 S imm10, second 11 J1 1 J2 imm11 (BL) or 11 J1 0 J2 (BLX)
for i in range(len(hw) - 1):
    h1 = hw[i]
    if h1 & 0xf800 != 0xf000:
        continue
    h2 = hw[i + 1]
    if h2 & 0xd000 != 0xd000:
        continue
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s:
        imm -= 1 << 25
    t = 2 * i + 4 + imm
    if 0 <= t < n:
        targets.add(t)
bl = len(targets)
# function pointers: odd 32-bit words pointing into the image
for i in range(0, n - 3, 4):
    v = struct.unpack_from('<I', d, i)[0]
    if v & 1 and base <= v < base + n:
        targets.add((v & ~1) - base)
seeds = sorted(t for t in targets if is_push(t))
with open(out, 'w') as f:
    for t in seeds:
        f.write('%x\n' % (base + t))
print(f'{path}: call targets {bl}, with pointers {len(targets)}, push-starting seeds {len(seeds)}')
