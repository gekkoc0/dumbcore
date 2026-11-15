#!/usr/bin/env python3
"""Writer for SPML vector fonts ('sfon') - inverse of tools/sfon.py. Big-endian throughout.

Glyph encoding rules are fitted so that every stock glyph re-encodes byte for byte (work/sfonwrite_test.py).
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ON, XSHORT, YSHORT, REPEAT, XSAME, YSAME, CUBIC = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40


# ------------------------------------------------------------------ glyph
def encode_simple(contours, rep_min=1, zero='short'):
    """contours: [[(x, y, tag)]] tag 1 on-curve, 0 quadratic control, 2 cubic control (font units, integers).
    -> bytes of the type-3 simple outline body (after the glyph flag/advance bytes)."""
    pts = [p for c in contours for p in c]
    n, nc = len(pts), len(contours)
    ends, e = [], -1
    for c in contours:
        e += len(c)
        ends.append(e)
    flags, xb, yb = [], bytearray(), bytearray()
    px = py = 0
    for x, y, t in pts:
        x, y = int(x), int(y)
        f = ON if t == 1 else (CUBIC if t == 2 else 0)
        dx, dy = x - px, y - py
        if dx == 0 and zero in ('same', 'xsame'):
            f |= XSAME
        elif -255 <= dx <= 255:
            f |= XSHORT | (XSAME if dx >= 0 else 0)
            xb.append(abs(dx))
        else:
            xb += struct.pack('>h', dx)
        if dy == 0 and zero in ('same', 'ysame'):
            f |= YSAME
        elif -255 <= dy <= 255:
            f |= YSHORT | (YSAME if dy >= 0 else 0)
            yb.append(abs(dy))
        else:
            yb += struct.pack('>h', dy)
        flags.append(f)
        px, py = x, y
    fb = bytearray()
    i = 0
    while i < n:
        j = i
        while j + 1 < n and flags[j + 1] == flags[i] and j + 1 - i < 255:
            j += 1
        run = j - i
        if run >= rep_min:
            fb += bytes((flags[i] | REPEAT, run))
            i = j + 1
        else:
            fb.append(flags[i])
            i += 1
    h = (1 if n < 256 else 0) | (2 if nc < 256 else 0) | (4 if ends and ends[-1] < 256 else 0)
    out = bytearray([h])
    out += bytes([n]) if h & 1 else struct.pack('>H', n)
    out += bytes([nc]) if h & 2 else struct.pack('>H', nc)
    out += fb + xb + yb
    for e in ends:
        out += bytes([e]) if h & 4 else struct.pack('>H', e)
    return bytes(out)


def encode_composite(comps):
    """comps: [dict(flags, gid, dx, dy, m)] as returned by Sfon._composite (flags kept as stored)."""
    out = bytearray(struct.pack('>H', len(comps)))
    for c in comps:
        fl = c['flags']
        out += struct.pack('>HH', fl, c['gid'])
        out += struct.pack('>hh', c['dx'], c['dy']) if fl & 1 else struct.pack('>bb', c['dx'], c['dy'])
        a, b, cc, e = c['m']
        f2 = lambda v: int(round(v * 16384))
        if fl & 8:
            out += struct.pack('>h', f2(a))
        elif fl & 0x40:
            out += struct.pack('>hh', f2(a), f2(e))
        elif fl & 0x80:
            out += struct.pack('>hhhh', f2(a), f2(b), f2(cc), f2(e))
    return bytes(out)


def encode_glyph(advance, default_advance, contours=None, composite=None, flags=None):
    """whole glyph record: flag byte, [advance byte], outline."""
    f = flags if flags is not None else ((0x01 if composite is not None else 0) | (0x08 if advance != default_advance else 0))
    out = bytearray([f])
    if f & 0x08:
        out.append(advance)
    out += encode_composite(composite) if composite is not None else encode_simple(contours or [])
    return bytes(out)


# ------------------------------------------------------------------ cmap (OpenType format 4, platform 3/1)
def build_cmap(mapping):
    """mapping {codepoint: gid} (BMP only) -> cmap table bytes: one format-4 subtable (platform 3, encoding 1), like
    the stock fonts. One segment per run of consecutive codepoints: idDelta if the gids are consecutive as well,
    otherwise idRangeOffset into glyphIdArray. The table is padded to 4 bytes (stock tables are too).
    Not byte-identical to the stock tables (their tool merges runs across gaps), but the same format."""
    cps = sorted(c for c in mapping if c < 0xffff and mapping[c])
    runs = []
    for c in cps:
        if runs and c == runs[-1][-1] + 1:
            runs[-1].append(c)
        else:
            runs.append([c])
    S = len(runs) + 1
    ends, starts, deltas, ranges, gia = [], [], [], [], []
    for r in runs:
        starts.append(r[0]); ends.append(r[-1])
        consec = all(mapping[r[i + 1]] - mapping[r[i]] == 1 for i in range(len(r) - 1))
        if consec:
            deltas.append((mapping[r[0]] - r[0]) & 0xffff); ranges.append(None)
        else:
            deltas.append(0); ranges.append(len(gia)); gia += [mapping[c] for c in r]
    starts.append(0xffff); ends.append(0xffff); deltas.append(1); ranges.append(None)
    ro = []
    for k, r in enumerate(ranges):
        ro.append(0 if r is None else 2 * (S - k) + 2 * r)       # bytes from this idRangeOffset slot to gia[r]
    search, sel = 1, 0
    while search * 2 <= S:
        search *= 2; sel += 1
    body = (struct.pack('>%dH' % S, *ends) + b'\0\0' + struct.pack('>%dH' % S, *starts)
            + struct.pack('>%dH' % S, *deltas) + struct.pack('>%dH' % S, *ro) + struct.pack('>%dH' % len(gia), *gia))
    length = 14 + len(body)
    if length > 0xffff:
        raise ValueError('cmap subtable too large for format 4')
    sub = struct.pack('>HHHHHHH', 4, length, 0, 2 * S, 2 * search, sel, 2 * S - 2 * search) + body
    t = struct.pack('>HHHHI', 0, 1, 3, 1, 12) + sub
    return t + b'\0' * (-len(t) & 3)


# ------------------------------------------------------------------ strike + file
def build_strike(glyphs, size, default_advance, line_a, line_b, kind=3, extra_hdr=None):
    """glyphs {gid: glyph bytes} -> strike bytes. Header 0x22 (see docs/sfon-format.md), segments of consecutive gids,
    u32 offsets relative to strike start + 0x20, glyph data back to back in gid order."""
    gids = sorted(glyphs)
    segs = []
    for g in gids:
        if segs and g == segs[-1][1] + 1:
            segs[-1][1] = g
        else:
            segs.append([g, g])
    S, n = len(segs), len(gids)
    hdr = bytearray(extra_hdr or bytes(0x22))
    hdr[0] = size
    hdr[0x10] = default_advance
    hdr[0x15], hdr[0x16], hdr[0x17], hdr[0x18] = line_a, line_b, kind, size
    struct.pack_into('>H', hdr, 0x1a, n)
    struct.pack_into('>I', hdr, 0x1c, 0x20)
    struct.pack_into('>H', hdr, 0x20, S)
    first, acc = [], 0
    for a, b in segs:
        first.append(acc)
        acc += b - a + 1
    tbl = struct.pack('>%dH' % S, *[b for a, b in segs]) + struct.pack('>%dH' % S, *[a for a, b in segs]) + struct.pack('>%dH' % S, *first)
    data_start = 0x22 + len(tbl) + 4 * n
    offs, data = [], bytearray()
    for g in gids:
        offs.append(data_start + len(data) - 0x20)
        data += glyphs[g]
    return bytes(hdr) + tbl + struct.pack('>%dI' % n, *offs) + bytes(data)


def build_sfon(script, upem, cmap, strike, gdef=b'', gsub=b'', gpos=b'', field10=1):
    """assemble: 0x2c header, cmap, GDEF, GSUB, GPOS, strike (stock order, no padding)."""
    tag = script.encode('latin-1')[:4].ljust(4, b'\0')
    body, offs, pos = bytearray(), [], 0x2c
    for t in (cmap, gdef, gsub, gpos):
        offs.append(pos if t else 0)
        body += t
        pos += len(t)
    hdr = b'sfon' + struct.pack('>I', 1) + tag + struct.pack('>HHHH', 3, 1, field10, upem)
    hdr += struct.pack('>5I', *offs, 0) + struct.pack('>I', pos)
    return hdr + bytes(body) + strike
