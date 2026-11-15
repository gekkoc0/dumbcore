#!/usr/bin/env python3
"""SMOV animation (Unisoc alpha_res_decoder.c, KERNEL 0x80ba681c) -> frames.

  0x00 'SMOV' 'ARGB'
  0x08 u16be X        (stored into image-info +8; 24 in every stock file — meaning not confirmed, likely fps/delay)
  0x0a u16be n_frames
  0x0c u32   0
  0x10 u32be offset[n_frames]   (from file start)
  ...  n_frames ABMP images (tools/imgcodec.py), frame i = blob[offset[i]:offset[i+1]]
Image info type = 7; width/height come from the first frame's ABMP header.

    smov.py <in.smov> <out_prefix>   -> <out_prefix>.gif
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imgcodec import decode_any


def parse(b):
    assert b[:8] == b'SMOVARGB', b[:8]
    x, n = struct.unpack_from('>HH', b, 8)
    offs = list(struct.unpack_from('>%dI' % n, b, 0x10))
    return {'x': x, 'n': n, 'offsets': offs}


def smov_frames(b):
    info = parse(b)
    offs = info['offsets'] + [len(b)]
    return [decode_any(b[offs[i]:offs[i + 1]]) for i in range(info['n'])]


if __name__ == '__main__':
    data = open(sys.argv[1], 'rb').read()
    print(parse(data))
    from PIL import Image
    ims = [Image.frombytes('RGBA', (w, h), bytes(px)) for w, h, px in smov_frames(data)]
    ims[0].save(sys.argv[2] + '.gif', save_all=True, append_images=ims[1:], duration=100, loop=0, disposal=2)
