#!/usr/bin/env python3
"""Encoder for ABMP / ABMR (Unisoc MOCOR alpha bitmaps), the inverse of tools/imgcodec.py.

Two layers:
  * pack(kind, w, h, a, b, box, palette565, alpha, idx_rows)  - exact container writer (used to re-encode stock images
    byte for byte, which proves the format rules);
  * encode_rgba(w, h, rgba, kind='P'|'R')                       - new image from RGBA pixels: builds the palette
    (opaque colours first, then semi-transparent ones), the bounding box and the index stream.
Only the 16-bit-palette kinds P and R are produced (the firmware also reads S/T/Q/U).
"""
import struct, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imgcodec import parse_abm, BitReader


def bits_for(N):
    bits = 1
    while (2 << (bits - 1)) < N and bits < 16:
        bits += 1
    return bits


# ------------------------------------------------------------------ bit packing
def pack_bits(values, bits, big_endian, r_tail=False):
    """values packed LSB-first into 16-bit words.
    P (big_endian): whole words. R (r_tail): 2*(nbits//16) bytes + 1 if 1..8 bits remain, else + 2
    (a full last word gets an extra empty word) - exactly what the stock encoder writes."""
    words, acc, n = [], 0, 0
    for v in values:
        acc |= v << n
        n += bits
        while n >= 16:
            words.append(acc & 0xffff)
            acc >>= 16
            n -= 16
    if n:
        words.append(acc & 0xffff)
    if r_tail and n == 0:
        words.append(0)
    out = b''.join(struct.pack('>H' if big_endian else '<H', x) for x in words)
    if r_tail and 0 < n <= 8:
        out = out[:-1]
    return out


# ------------------------------------------------------------------ decoding to indices
def decode_indices(b):
    """-> header dict + rows of indices inside the box, + for R: list of (n, f) pairs per row."""
    H = parse_abm(b)
    x0, y0, x1, y1, bits = H['x0'], H['y0'], H['x1'], H['y1'], H['bits']
    cw = x1 - x0 + 1
    rows, runs = [], []
    if H['kind'] in 'PSQ':
        br = BitReader(b, H['data'])
        for y in range(y0, y1 + 1):
            rows.append([br.read(bits) for _ in range(cw)])
    else:
        p = H['data']
        L, = struct.unpack_from('<I', b, p)
        r = p + 4
        br = BitReader(b, p + 4 + L, big_endian=False)
        for y in range(y0, y1 + 1):
            row, pairs = [], []
            while True:
                n, f = b[r], b[r + 1]
                r += 2
                pairs.append((n, f))
                if n == 0 and f == 0:
                    break
                row += [br.read(bits) for _ in range(n)]
                if f:
                    row += [br.read(bits)] * f
            rows.append(row)
            runs.append(pairs)
    return H, rows, runs


# ------------------------------------------------------------------ R row runs
def row_runs(row, min_rep=3, max_n=255, end_rep=1):
    """split a row into (literals, repeat) pairs. Rule fitted on stock files (work/imgenc_test.py):
    a run becomes a repeat from min_rep equal values, the run that ends the row is always a repeat (end_rep=1)."""
    pairs, stream = [], []
    i, n = 0, len(row)
    lit = []
    while i < n:
        j = i
        while j < n and row[j] == row[i]:
            j += 1
        run = j - i
        if run >= (end_rep if j == n else min_rep):
            while run:
                take = min(run, max_n)
                pairs.append((len(lit), take))
                stream += lit + [row[i]]
                lit = []
                run -= take
            i = j
        else:
            for _ in range(run):
                lit.append(row[i])
                if len(lit) == max_n:
                    pairs.append((max_n, 0))
                    stream += lit
                    lit = []
            i = j
    if lit:
        pairs.append((len(lit), 0))
        stream += lit
    pairs.append((0, 0))
    return pairs, stream


# ------------------------------------------------------------------ container
def pack(kind, w, h, a, b, box, palette565, alpha, rows, runs=None, min_rep=3):
    """box = (top, left, bottom, right) margins; palette565 = N-1 colours; alpha = b values; rows = box rows of indices."""
    assert kind in 'PR'
    N = a + b
    bits = bits_for(N)
    top, left, bottom, right = box
    hdr = b'ABM' + kind.encode() + struct.pack('>HHHH', w, h, a, b) + bytes(box)
    body = b''.join(struct.pack('>H', c) for c in palette565) + bytes(alpha)
    out = hdr + body
    if len(out) & 1:
        out += b'\xff'                                  # alignment filler is 0xFF in stock files
    if kind == 'P':
        flat = [v for r in rows for v in r]
        out += pack_bits(flat, bits, True)
    else:
        rb, stream = bytearray(), []
        for y, r in enumerate(rows):
            if runs is not None:
                pairs = runs[y]
                pos = 0
                for n, f in pairs:
                    stream += r[pos:pos + n]
                    pos += n
                    if f:
                        stream.append(r[pos])
                        pos += f
            else:
                pairs, s = row_runs(r, min_rep)
                stream += s
            for n, f in pairs:
                rb += bytes((n, f))
        out += struct.pack('<I', len(rb)) + bytes(rb) + pack_bits(stream, bits, False, r_tail=True)
    return out


# ------------------------------------------------------------------ from RGBA
def to565(r, g, b):
    return (r >> 3) << 11 | (g >> 2) << 5 | b >> 3


SEMI_KEY = lambda k: (k[1], k[0])   # (alpha, colour), both descending


def encode_rgba(w, h, rgba, kind='P', alpha_cut=8, crop=True):
    """RGBA bytes -> ABMP/ABMR. Pixels with alpha < alpha_cut become transparent (index 0).
    Colours are quantised to RGB565; alpha kept as 8 bits. Raises if more than 65535 entries are needed."""
    px = [tuple(rgba[i:i + 4]) for i in range(0, w * h * 4, 4)]
    keyed = []
    for (r, g, b, a) in px:
        if a < alpha_cut:
            keyed.append(None)
        else:
            keyed.append((to565(r, g, b), a))
    vis = [i for i, k in enumerate(keyed) if k is not None]
    if not vis:
        box = (0, 0, h - 1, w - 1) if h and w else (0, 0, 0, 0)
        ys = xs = [0]
    ys = [i // w for i in vis] or [0]
    xs = [i % w for i in vis] or [0]
    y0, y1, x0, x1 = min(ys), max(ys), min(xs), max(xs)
    if not crop:                                  # SMOV frames: box is always the whole frame
        y0, y1, x0, x1 = 0, h - 1, 0, w - 1
    box = (y0, x0, h - 1 - y1, w - 1 - x1)
    # stock order (measured on all 2062 stock images): opaque colours by RGB565 descending,
    # semi-transparent entries by SEMI_KEY (see work/imgenc_rgba_test.py)
    opaque = sorted({k[0] for k in keyed if k and k[1] == 255}, reverse=True)
    semi = sorted({k for k in keyed if k and k[1] != 255}, key=SEMI_KEY, reverse=True)
    a = len(opaque) + 1
    b = len(semi)
    if a + b > 0xffff:
        raise ValueError('too many colours; reduce the palette first')
    index = {(c, 255): i + 1 for i, c in enumerate(opaque)}
    for j, key in enumerate(semi):
        index[key] = a + j
    palette = opaque + [c for c, _ in semi]
    alpha = [al for _, al in semi]
    rows = []
    for y in range(y0, y1 + 1):
        rows.append([0 if keyed[y * w + x] is None else index[keyed[y * w + x]] for x in range(x0, x1 + 1)])
    return pack(kind, w, h, a, b, box, palette, alpha, rows)
