#!/usr/bin/env python3
"""Reader for Unisoc SPML vector fonts ('sfon'), as stored in mmi_res font resources.

Layout (from user image spml_font.c, loader 0x88079ac0, glyph lookup 0x880791b0; all big-endian):
  +0x00 'sfon'  +0x04 u32 sprd_version=1  +0x08 script tag ('latn','cyrl'...)
  +0x0c u16 font_version=3  +0x0e u16 n_strikes
  +0x10 u16 ?(1)  +0x12 u16 units_per_em
  +0x14 u32 off cmap  +0x18 GDEF  +0x1c GSUB  +0x20 GPOS  +0x24 kern   (0 = absent; OpenType layouts)
  +0x28 u32 strike_off[n_strikes]
  strike: 0x22-byte header: +0 u8 ppem/design size, +0x17 u8 type (3,4 = scalable outline),
          +0x1a u16 n_glyphs, +0x20 u16 n_segments
          then u16 end[S], u16 start[S], u16 first_index[S], u32 glyph_off[n_glyphs]
          glyph g in segment k: index = first_index[k] + g - start[k];
          data at strike_off + glyph_off[index] + 0x20, size = next offset - this.
"""
import struct, sys


def u16(b, o): return struct.unpack_from('>H', b, o)[0]
def u32(b, o): return struct.unpack_from('>I', b, o)[0]


class Sfon:
    def __init__(self, b):
        assert b[:4] == b'sfon'
        self.b = b
        self.script = b[8:12].rstrip(b'\0').decode()
        self.version, self.n_strikes = u16(b, 0x0c), u16(b, 0x0e)
        self.upem = u16(b, 0x12)
        self.tables = dict(zip(('cmap', 'GDEF', 'GSUB', 'GPOS', 'kern'), struct.unpack_from('>5I', b, 0x14)))
        self.strike_offs = [u32(b, 0x28 + 4 * i) for i in range(self.n_strikes)]
        self.cmap = self._cmap(self.tables['cmap'])
        self.strikes = [self._strike(i) for i in range(self.n_strikes)]

    def _cmap(self, off):
        b = self.b
        n = u16(b, off + 2)
        for i in range(n):
            pid, eid, sub = struct.unpack_from('>HHI', b, off + 4 + 8 * i)
            o = off + sub
            if u16(b, o) == 4:
                segx2 = u16(b, o + 6)
                S = segx2 // 2
                ends = struct.unpack_from('>%dH' % S, b, o + 14)
                starts = struct.unpack_from('>%dH' % S, b, o + 16 + segx2)
                deltas = struct.unpack_from('>%dh' % S, b, o + 16 + 2 * segx2)
                ro_base = o + 16 + 3 * segx2
                ranges = struct.unpack_from('>%dH' % S, b, ro_base)
                m = {}
                for k in range(S):
                    for c in range(starts[k], ends[k] + 1):
                        if c == 0xffff:
                            continue
                        if ranges[k] == 0:
                            g = (c + deltas[k]) & 0xffff
                        else:
                            p = ro_base + 2 * k + ranges[k] + 2 * (c - starts[k])
                            g = u16(b, p)
                            if g:
                                g = (g + deltas[k]) & 0xffff
                        if g:
                            m[c] = g
                return m
        return {}

    def _strike(self, i):
        b, so = self.b, self.strike_offs[i]
        end = self.strike_offs[i + 1] if i + 1 < self.n_strikes else len(b)
        hdr = b[so:so + 0x22]
        n, S = u16(hdr, 0x1a), u16(hdr, 0x20)
        p = so + 0x22
        ends = struct.unpack_from('>%dH' % S, b, p)
        starts = struct.unpack_from('>%dH' % S, b, p + 2 * S)
        first = struct.unpack_from('>%dH' % S, b, p + 4 * S)
        offs = struct.unpack_from('>%dI' % n, b, p + 6 * S)
        return dict(off=so, end=end, hdr=hdr, size=hdr[0], type=hdr[0x17], n=n, S=S,
                    ends=ends, starts=starts, first=first, offs=offs, tbl_end=p + 6 * S + 4 * n)

    def glyph(self, gid, strike=0):
        st = self.strikes[strike]
        for k in range(st['S']):
            if st['starts'][k] <= gid <= st['ends'][k]:
                idx = st['first'][k] + gid - st['starts'][k]
                a = st['off'] + st['offs'][idx] + 0x20
                z = (st['off'] + st['offs'][idx + 1] + 0x20) if idx + 1 < st['n'] else st['end']
                return self.b[a:z]
        return None


    # ---- glyph decoding (user image spml_font.c 0x8807957a, spml_image.c 0x884ed954 / 0x884ed168) ----
    def glyph_record(self, gid, strike=0):
        """-> dict(flags, advance, composite|None, contours) in font units (y up)."""
        d = self.glyph(gid, strike)
        if not d:
            return None
        st = self.strikes[strike]
        f = d[0]
        p = 1
        adv = st['hdr'][0x10]
        if f & 0x08:
            adv = d[p]; p += 1
        rec = dict(flags=f, advance_raw=adv, composite=None, contours=[])
        if f & 0x01:
            rec['composite'] = self._composite(d, p)
        else:
            rec['contours'] = self._simple(d, p)
        return rec

    @staticmethod
    def _simple(d, p):
        """type-3 simple outline: TrueType-like, ends at the tail. points: (x, y, tag) tag 1=on, 0=conic, 2=cubic."""
        h = d[p]; p += 1
        if h & 1:
            n = d[p]; p += 1
        else:
            n = u16(d, p); p += 2
        if h & 2:
            nc = d[p]; p += 1
        else:
            nc = u16(d, p); p += 2
        flags = []
        while len(flags) < n:
            fl = d[p]; p += 1
            flags.append(fl)
            if fl & 8:
                r = d[p]; p += 1
                flags.extend([fl] * r)
        xs, ys, x, y = [], [], 0, 0
        for fl in flags:
            if fl & 2:
                v = d[p]; p += 1
                x += v if fl & 0x10 else -v
            elif not fl & 0x10:
                x += struct.unpack_from('>h', d, p)[0]; p += 2
            xs.append(x)
        for fl in flags:
            if fl & 4:
                v = d[p]; p += 1
                y += v if fl & 0x20 else -v
            elif not fl & 0x20:
                y += struct.unpack_from('>h', d, p)[0]; p += 2
            ys.append(y)
        ends = []
        for _ in range(nc):
            if h & 4:
                ends.append(d[p]); p += 1
            else:
                ends.append(u16(d, p)); p += 2
        pts = [(xs[i], ys[i], 1 if flags[i] & 1 else (2 if flags[i] & 0x40 else 0)) for i in range(n)]
        out, s = [], 0
        for e in ends:
            out.append(pts[s:e + 1]); s = e + 1
        return out

    @staticmethod
    def _composite(d, p):
        cnt = u16(d, p); p += 2
        comps = []
        for _ in range(cnt):
            fl, gid = u16(d, p), u16(d, p + 2); p += 4
            if fl & 1:
                dx, dy = struct.unpack_from('>hh', d, p); p += 4
            else:
                dx, dy = struct.unpack_from('>bb', d, p); p += 2
            m = (1.0, 0.0, 0.0, 1.0)
            if fl & 8:
                s = struct.unpack_from('>h', d, p)[0] / 16384; p += 2; m = (s, 0, 0, s)
            elif fl & 0x40:
                a, b = struct.unpack_from('>hh', d, p); p += 4; m = (a / 16384, 0, 0, b / 16384)
            elif fl & 0x80:
                a, b, c, e = struct.unpack_from('>hhhh', d, p); p += 8
                m = (a / 16384, b / 16384, c / 16384, e / 16384)
            comps.append(dict(flags=fl, gid=gid, dx=dx, dy=dy, m=m))
        return comps

    def outline(self, gid, depth=0):
        """resolved contours (composites expanded)."""
        r = self.glyph_record(gid)
        if not r:
            return []
        if r['composite'] is None:
            return r['contours']
        res = []
        for c in r['composite']:
            a, b, cc, e = c['m']
            for con in self.outline(c['gid'], depth + 1) if depth < 8 else []:
                res.append([(a * x + cc * y + c['dx'], b * x + e * y + c['dy'], t) for x, y, t in con])
        return res


def flatten(contour, steps=8):
    """contour points (x,y,tag) -> polygon. Handles TrueType conic (implied on-points) and cubic pairs."""
    pts = list(contour)
    if not pts:
        return []
    # rotate so we start at an on-curve point
    k = next((i for i, q in enumerate(pts) if q[2] == 1), None)
    if k is None:
        a, b = pts[0], pts[1 % len(pts)]
        pts.insert(0, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 1)); k = 0
    pts = pts[k:] + pts[:k] + [pts[k]]
    poly = [pts[0][:2]]
    i = 1
    while i < len(pts):
        x, y, t = pts[i]
        if t == 1:
            poly.append((x, y)); i += 1
        elif t == 2:  # cubic: two control points then on point
            c1, c2, e = pts[i], pts[i + 1], pts[i + 2] if i + 2 < len(pts) else pts[0]
            s = poly[-1]
            for j in range(1, steps + 1):
                u = j / steps; v = 1 - u
                poly.append((v**3 * s[0] + 3 * v * v * u * c1[0] + 3 * v * u * u * c2[0] + u**3 * e[0],
                             v**3 * s[1] + 3 * v * v * u * c1[1] + 3 * v * u * u * c2[1] + u**3 * e[1]))
            i += 3
        else:  # conic
            c = pts[i]
            nx = pts[i + 1]
            e = nx if nx[2] == 1 else ((c[0] + nx[0]) / 2, (c[1] + nx[1]) / 2, 1)
            s = poly[-1]
            for j in range(1, steps + 1):
                u = j / steps; v = 1 - u
                poly.append((v * v * s[0] + 2 * v * u * c[0] + u * u * e[0], v * v * s[1] + 2 * v * u * c[1] + u * u * e[1]))
            i += 1 if nx[2] != 1 else 2
    return poly


def raster(polys, w, h, ss=4):
    """non-zero fill; polys in pixel coords (y down). -> coverage bytes w*h."""
    cov = bytearray(w * h)
    edges = []
    for poly in polys:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
            if y0 != y1:
                edges.append((x0, y0, x1, y1, 1 if y1 > y0 else -1))
    for py in range(h):
        acc = [0] * w
        for sy in range(ss):
            yy = py + (sy + 0.5) / ss
            xs = []
            for x0, y0, x1, y1, wd in edges:
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    xs.append((x0 + (yy - y0) * (x1 - x0) / (y1 - y0), wd))
            xs.sort()
            wind = 0
            for (xa, wa), (xb, _) in zip(xs, xs[1:]):
                wind += wa
                if wind:
                    for sx in range(ss):
                        lo, hi = xa * ss - sx, xb * ss - sx
                        a = max(0, int(lo // ss) if lo > 0 else 0)
                        for px in range(max(0, int(xa)), min(w, int(xb) + 1)):
                            c = px + (sx + 0.5) / ss
                            if xa <= c < xb:
                                acc[px] += 1
        for px in range(w):
            cov[py * w + px] = min(255, acc[px] * 255 // (ss * ss))
    return cov


def render_text(font, text, px=48, margin=8, fallback=()):
    """render a string; returns (w, h, rgba). fallback: other Sfon fonts tried for missing chars."""
    fonts = (font,) + tuple(fallback)
    scale = px / font.upem
    glyphs, x = [], margin
    for ch in text:
        f = next((ff for ff in fonts if ord(ch) in ff.cmap), font)
        s = px / f.upem
        gid = f.cmap.get(ord(ch))
        rec = f.glyph_record(gid) if gid else None
        adv = (rec['advance_raw'] / 32 * px) if rec else px / 3
        # advance unit: strike-relative 1/32 of size (from 0x88079740: adv*scale/32)
        polys = [[(x + gx * s, gy * s) for gx, gy in flatten(c)] for c in (f.outline(gid) if gid else [])]
        glyphs.append(polys)
        x += adv
    W, H = int(x + margin), int(px * 1.4 + 2 * margin)
    base = margin + px * 1.05
    polys = [[(gx, base - gy) for gx, gy in p] for g in glyphs for p in g]
    cov = raster(polys, W, H)
    rgba = bytearray(W * H * 4)
    for i, c in enumerate(cov):
        v = 255 - c
        rgba[i * 4:i * 4 + 4] = bytes((v, v, v, 255))
    return W, H, rgba


if __name__ == '__main__':
    f = Sfon(open(sys.argv[1], 'rb').read())
    print(f.script, 'upem', f.upem, 'strikes', f.n_strikes, 'tables', {k: hex(v) for k, v in f.tables.items()})
    print('cmap chars', len(f.cmap))
    for st in f.strikes:
        print(' strike size', st['size'], 'type', st['type'], 'glyphs', st['n'], 'segments', st['S'],
              'hdr', st['hdr'].hex(' '))
