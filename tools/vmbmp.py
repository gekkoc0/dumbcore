#!/usr/bin/env python3
"""'VM' multi-frame BMP (Unisoc bmp_io.c / bmp_decoder.c) -> frames.

Layout (all little-endian, it is a BMP with a different magic):
  0x00 'VM'  u32 file_size  u32 key_rgb888 (bfReserved; transparent colour of delta frames)  u32 data_off
  0x0e BITMAPINFOHEADER (40): w, h, planes, bpp, compression, ...  (+ 3 masks when compression&0xfff == 3)
  data_off: u32 n_frames, then n_frames * {u32 size_flags, u32 offset}   (offset from file start)
            size_flags bit31 = 1 -> frame stored raw, 0 -> frame RLE-compressed (decoder ORs 0x1000 into compression)
Frame rows are bottom-up. RLE row (16 bpp, KERNEL 0x81306488): repeated segments
  u8 n_lit, u8 n_rep, n_lit * u16 pixels, [u16 pixel repeated n_rep times if n_rep]; '00 00' ends the row.
Frame 0 is drawn whole; frames 1.. are drawn with the key colour transparent (delta over the previous frame).
KERNEL refs: header 0x80ba4878, frame select 0x81307cc2, frame decode 0x813072a2, key 0x80ba4838.

    vmbmp.py <in.vm> <out_prefix>     -> <out_prefix>.gif (+ _NN.png per frame)
"""
import struct, sys


def parse(b):
    assert b[:2] == b'VM', b[:2]
    size, key, data_off = struct.unpack_from('<III', b, 2)
    hdr_size, w, h, planes, bpp, comp = struct.unpack_from('<IiiHHI', b, 0x0e)
    masks = struct.unpack_from('<III', b, 0x36) if (comp & 0xfff) == 3 else None
    n, = struct.unpack_from('<I', b, data_off)
    frames = []
    for i in range(n):
        sf, off = struct.unpack_from('<II', b, data_off + 4 + 8 * i)
        frames.append({'raw': bool(sf & 0x80000000), 'size': sf & 0x7fffffff, 'off': off})
    return {'size': size, 'key': key, 'w': w, 'h': h, 'bpp': bpp, 'comp': comp, 'masks': masks, 'frames': frames}


def key565(key):
    r, g, bl = (key >> 16) & 0xff, (key >> 8) & 0xff, key & 0xff
    return (r >> 3) << 11 | (g >> 2) << 5 | bl >> 3


def rle_row(b, p, w):
    px = []
    while True:
        lit, rep = b[p], b[p + 1]
        p += 2
        if lit == 0 and rep == 0:
            break
        for _ in range(lit):
            px.append(struct.unpack_from('<H', b, p)[0])
            p += 2
        if rep:
            px.extend([struct.unpack_from('<H', b, p)[0]] * rep)
            p += 2
    assert len(px) == w, (len(px), w)
    return px, p


def bmp_rle565(b):
    """plain 'BM' file with compression 0x1003 (RGB565 + the same row RLE) -> (w, h, RGBA bytes).
    Used by the mmi_res 'logo' sections (boot/shutdown logos)."""
    assert b[:2] == b'BM'
    data_off, = struct.unpack_from('<I', b, 10)
    _, w, h, _, bpp, comp = struct.unpack_from('<IiiHHI', b, 0x0e)
    assert bpp == 16
    rows, p = [], data_off
    for _ in range(abs(h)):
        if comp & 0x1000:
            row, p = rle_row(b, p, w)
        else:
            row = list(struct.unpack_from('<%dH' % w, b, p))
            p += (w * 2 + 3) & ~3
        rows.append(row)
    if h > 0:
        rows.reverse()
    px = bytearray()
    for row in rows:
        for v in row:
            px += bytes(((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255))
    return w, abs(h), bytes(px)


def frames565(b):
    """yield list-of-rows (top-down) of RGB565 values, None = transparent (keyed) pixel."""
    info = parse(b)
    assert info['bpp'] == 16, 'only 16 bpp seen in firmware'
    w, h, key = info['w'], abs(info['h']), key565(info['key'])
    stride = (w * 2 + 3) & ~3
    for i, f in enumerate(info['frames']):
        rows = []
        p = f['off']
        for _ in range(h):
            if f['raw']:
                row = list(struct.unpack_from('<%dH' % w, b, p))
                p += stride
            else:
                row, p = rle_row(b, p, w)
            if i > 0:
                row = [None if v == key else v for v in row]
            rows.append(row)
        if info['h'] > 0:
            rows.reverse()
        yield rows


def rgba_frames(b):
    """composite delta frames -> list of (w, h, RGBA bytes)."""
    info = parse(b)
    w, h = info['w'], abs(info['h'])
    canvas = [[0] * w for _ in range(h)]
    out = []
    for rows in frames565(b):
        for y in range(h):
            for x in range(w):
                if rows[y][x] is not None:
                    canvas[y][x] = rows[y][x]
        px = bytearray()
        for y in range(h):
            for v in canvas[y]:
                px += bytes(((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255))
        out.append((w, h, bytes(px)))
    return out


if __name__ == '__main__':
    data = open(sys.argv[1], 'rb').read()
    info = parse(data)
    print({k: v for k, v in info.items() if k != 'frames'})
    for f in info['frames']:
        print('  frame', f)
    from PIL import Image
    ims = [Image.frombytes('RGBA', (w, h), px) for w, h, px in rgba_frames(data)]
    for i, im in enumerate(ims):
        im.save(f'{sys.argv[2]}_{i:02d}.png')
    ims[0].save(sys.argv[2] + '.gif', save_all=True, append_images=ims[1:], duration=150, loop=0)
