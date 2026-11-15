#!/usr/bin/env python3
"""Guess the load address of a raw ARM image by voting: base = pointer - string_offset.
Assumes the base is 0x1000-aligned. Usage: findbase.py image.bin [payload_offset]"""
import sys, re, struct, collections

path = sys.argv[1]
skip = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x200   # DHTB header
d = open(path, 'rb').read()[skip:]

strings = [m.start() for m in re.finditer(rb'[\x20-\x7e]{6,}\x00', d)]
by_low = collections.defaultdict(list)
for s in strings:
    by_low[s & 0xfff].append(s)

words = struct.unpack_from('<%dI' % (len(d) // 4), d)
votes = collections.Counter()
for w in set(words):
    if not (0x10000000 <= w < 0xf0000000):
        continue
    for s in by_low.get(w & 0xfff, ()):
        b = w - s
        if b > 0:
            votes[b] += 1
for b, v in votes.most_common(5):
    print(f'base {b:#010x}  votes {v}')
