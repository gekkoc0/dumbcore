#!/usr/bin/env python3
"""Encoders for the remaining mmi_res formats (inverse of the readers), see docs/sres-format.md.

  ring_fmt(data)                      -> format code of a sound file (MIDI 0, WAV 5, MP3 6, AMR 8)
  bmp_encode(template, rgba)          -> 16-bit BMP like the stock ones (RLE 0x1003 or raw 0x3, header from template)
  sgif_wrap(gif_bytes)                -> 'SGIF' wrapper around a GIF89a file
  sabm_raw_encode(template, rgba)     -> 'sabm' with raw 32-bit pixels (wrapper header from template)
  sjpg_encode(rgb, w, h, level=4)     -> 'SJPG' wallpaper (baseline JPEG scan, 4:2:2, firmware quant tables)
  smov_encode(frames, x=24, kind)     -> 'SMOV' animation of ABMP/ABMR frames
Stock re-encoding checks: work/resenc_test.py.
"""
import struct, io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imgenc import row_runs, encode_rgba
import sjpg

RING_FMT = {b'MThd': 0x0, b'RIFF': 0x5, b'ID3': 0x6, b'\xff\xfb': 0x6, b'\xff\xf3': 0x6, b'\xff\xf2': 0x6, b'#!AMR': 0x8}


def ring_fmt(data):
    for magic, code in RING_FMT.items():
        if data.startswith(magic):
            return code
    raise ValueError('unknown sound format (MIDI, WAV, MP3 or AMR expected)')


def to565(r, g, b):
    return (r >> 3) << 11 | (g >> 2) << 5 | b >> 3


def rgba_rows565(w, h, rgba, bg=(0, 0, 0)):
    """RGBA -> rows of RGB565 (top-down). BMP has no alpha: pixels are blended onto bg."""
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b, a = rgba[(y * w + x) * 4:(y * w + x) * 4 + 4]
            if a < 255:
                r = (r * a + bg[0] * (255 - a)) // 255
                g = (g * a + bg[1] * (255 - a)) // 255
                b = (b * a + bg[2] * (255 - a)) // 255
            row.append(to565(r, g, b))
        rows.append(row)
    return rows


def bmp_encode(template, w, h, rows565):
    """header fields copied from the stock template (masks, DPI, compression, row padding style);
    data bottom-up. Compression 0x1003: each row = (n_lit, n_rep) pairs, u16 pixels, '00 00' ends the row,
    same splitting rule as ABMR (repeat from 3 equal pixels, the last run of a row always a repeat)."""
    hdr = bytearray(template[:66])
    off, = struct.unpack_from('<I', template, 10)
    assert off == 66, 'unexpected stock BMP layout'
    comp, = struct.unpack_from('<I', template, 30)
    isz_t, = struct.unpack_from('<I', template, 34)
    tw, th = struct.unpack_from('<ii', template, 18)
    data = bytearray()
    for row in reversed(rows565):
        if comp & 0x1000:
            pairs, stream = row_runs(row, 3, end_rep=1)
            k = 0
            for n, r in pairs:
                data += bytes((n, r))
                if n == 0 and r == 0:
                    break
                for v in stream[k:k + n]:
                    data += struct.pack('<H', v)
                k += n
                if r:
                    data += struct.pack('<H', stream[k]); k += 1
        else:
            line = b''.join(struct.pack('<H', v) for v in row)
            data += line + b'\0' * (-len(line) & 3)
    # (one stock raw BMP, 240x16, carries 2 extra zero bytes at the end - an artifact of the tool that drew it;
    #  not reproduced, the firmware reads by width/height)
    struct.pack_into('<ii', hdr, 18, w, h)
    struct.pack_into('<I', hdr, 2, 66 + len(data))
    struct.pack_into('<I', hdr, 34, len(data))
    return bytes(hdr + data)


def sgif_wrap(gif, w=None, h=None):
    """'SGIF', u16be 1, u16be width, u16be height, u16be 0, then the GIF file."""
    assert gif[:4] == b'GIF8', 'not a GIF file'
    gw, gh = struct.unpack_from('<HH', gif, 6)
    return b'SGIF' + struct.pack('>HHHH', 1, w or gw, h or gh, 0) + gif


def sabm_raw_encode(template, w, h, rgba):
    """'sabm' + 4 header bytes from the template + u16be w, h + w*h*4 bytes B,G,R,A."""
    out = bytearray(template[:8]) + struct.pack('>HH', w, h)
    px = bytearray(len(rgba))
    px[0::4], px[1::4], px[2::4], px[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
    return bytes(out + px)


def sjpg_encode(rgb_image, level=4, a=3):
    """PIL RGB image -> SJPG. Baseline JPEG with the firmware's quant tables of `level`, 4:2:2, standard Huffman
    tables; the SJPG keeps only the entropy-coded scan (with byte stuffing), no markers, no EOI."""
    from PIL import Image
    im = rgb_image.convert('RGB')
    w, h = im.size
    buf = io.BytesIO()
    im.save(buf, 'JPEG', qtables=[sjpg.LEVEL_LUMA[level], sjpg.LEVEL_CHROMA[level]], subsampling=1,
            optimize=False, progressive=False)
    j = buf.getvalue()
    p = 2
    scan = None
    while p < len(j):
        assert j[p] == 0xff
        mk = j[p + 1]
        ln, = struct.unpack_from('>H', j, p + 2)
        if mk == 0xdb:          # check the quant tables really are the firmware's (stored in zig-zag order)
            q = 2 + 2
            while q < 2 + ln:
                tid = j[p + q] & 15
                tab = (sjpg.LEVEL_LUMA if tid == 0 else sjpg.LEVEL_CHROMA)[level]
                assert list(j[p + q + 1:p + q + 65]) == [tab[sjpg.ZZ[i]] for i in range(64)], 'quant table mismatch'
                q += 65
        if mk == 0xc4:
            pass
        if mk == 0xda:
            start = p + 2 + ln
            end = j.rindex(b'\xff\xd9')
            scan = j[start:end]
            break
        p += 2 + ln
    return b'SJPG' + struct.pack('>HHHH', h, w, a, level) + scan


def smov_encode(frames, x=24, kind='P'):
    """frames: [(w, h, rgba)] -> 'SMOV' 'ARGB' u16be x, u16be n, u32 0, u32be offsets, ABM frames.
    Valid but not byte-identical to the stock animations: their tool sometimes shares one palette between frames."""
    blobs = [encode_rgba(w, h, rgba, kind=kind) for w, h, rgba in frames]
    n = len(blobs)
    pos = 0x10 + 4 * n
    offs = []
    for b in blobs:
        offs.append(pos)
        pos += len(b)
    return b'SMOVARGB' + struct.pack('>HHI', x, n, 0) + struct.pack('>%dI' % n, *offs) + b''.join(blobs)
