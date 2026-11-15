#!/usr/bin/env python3
"""Minimal TrueType (glyf) reader: .ttf and .ttc collections. Standard library only.

    ttf.py <font.ttf|.ttc> [face index]     # list faces / basic info

Gives: units per em, cmap (format 4 and 12), advance widths (hmtx), glyph outlines with composites resolved
(quadratic: points (x, y, tag) with tag 1 = on-curve, 0 = off-curve). CFF (.otf with PostScript outlines) is not
supported.
"""
import struct, sys


class TTF:
    def __init__(self, data, index=0):
        self.d = data
        base = 0
        if data[:4] == b'ttcf':
            n, = struct.unpack_from('>I', data, 8)
            offs = struct.unpack_from('>%dI' % n, data, 12)
            self.faces = n
            base = offs[index]
        else:
            self.faces = 1
        nt, = struct.unpack_from('>H', data, base + 4)
        self.t = {}
        for i in range(nt):
            tag, _, off, ln = struct.unpack_from('>4sIII', data, base + 12 + 16 * i)
            self.t[tag.decode('latin-1')] = (off, ln)
        if 'glyf' not in self.t:
            raise ValueError('no glyf table (CFF outlines are not supported)')
        h = self.t['head'][0]
        self.upem, = struct.unpack_from('>H', data, h + 18)
        self.loca_long, = struct.unpack_from('>h', data, h + 50)
        self.n_glyphs, = struct.unpack_from('>H', data, self.t['maxp'][0] + 4)
        hh = self.t['hhea'][0]
        self.ascent, self.descent, self.line_gap = struct.unpack_from('>hhh', data, hh + 4)
        self.n_hmetrics, = struct.unpack_from('>H', data, hh + 34)
        self.name = self._name()
        self.cmap = self._cmap()
        self._loca()

    # ----------------------------------------------------------------- tables
    def _name(self):
        if 'name' not in self.t:
            return ''
        o, _ = self.t['name']
        cnt, so = struct.unpack_from('>HH', self.d, o + 2)
        best = {}
        for i in range(cnt):
            pid, eid, lid, nid, ln, off = struct.unpack_from('>6H', self.d, o + 6 + 12 * i)
            if nid in (1, 2, 4):
                raw = self.d[o + so + off:o + so + off + ln]
                s = raw.decode('utf-16-be', 'replace') if pid in (0, 3) else raw.decode('latin-1')
                if pid == 3 and lid == 0x409 or nid not in best:
                    best[nid] = s
        return best.get(4) or (best.get(1, '') + ' ' + best.get(2, '')).strip()

    def _cmap(self):
        o, _ = self.t['cmap']
        n, = struct.unpack_from('>H', self.d, o + 2)
        subs = [struct.unpack_from('>HHI', self.d, o + 4 + 8 * i) for i in range(n)]
        pick = None
        for pid, eid, so in subs:                      # prefer full-Unicode format 12, then BMP format 4
            fmt, = struct.unpack_from('>H', self.d, o + so)
            if fmt == 12 and pid in (0, 3):
                pick = so
                break
        if pick is None:
            for pid, eid, so in subs:
                fmt, = struct.unpack_from('>H', self.d, o + so)
                if fmt == 4 and (pid, eid) in ((3, 1), (0, 3), (0, 4), (3, 10)):
                    pick = so
                    break
        m = {}
        p = o + pick
        fmt, = struct.unpack_from('>H', self.d, p)
        if fmt == 12:
            ng, = struct.unpack_from('>I', self.d, p + 12)
            for i in range(ng):
                a, b, g = struct.unpack_from('>III', self.d, p + 16 + 12 * i)
                for c in range(a, b + 1):
                    m[c] = g + c - a
        else:
            S = struct.unpack_from('>H', self.d, p + 6)[0] // 2
            ends = struct.unpack_from('>%dH' % S, self.d, p + 14)
            starts = struct.unpack_from('>%dH' % S, self.d, p + 16 + 2 * S)
            deltas = struct.unpack_from('>%dh' % S, self.d, p + 16 + 4 * S)
            rbase = p + 16 + 6 * S
            ros = struct.unpack_from('>%dH' % S, self.d, rbase)
            for k in range(S):
                for c in range(starts[k], ends[k] + 1):
                    if c == 0xffff:
                        continue
                    if ros[k] == 0:
                        g = (c + deltas[k]) & 0xffff
                    else:
                        g, = struct.unpack_from('>H', self.d, rbase + 2 * k + ros[k] + 2 * (c - starts[k]))
                        g = (g + deltas[k]) & 0xffff if g else 0
                    if g:
                        m[c] = g
        return m

    def _loca(self):
        o, _ = self.t['loca']
        n = self.n_glyphs + 1
        if self.loca_long:
            self.loca = struct.unpack_from('>%dI' % n, self.d, o)
        else:
            self.loca = [2 * v for v in struct.unpack_from('>%dH' % n, self.d, o)]

    def advance(self, gid):
        o, _ = self.t['hmtx']
        i = min(gid, self.n_hmetrics - 1)
        return struct.unpack_from('>H', self.d, o + 4 * i)[0]

    # ----------------------------------------------------------------- glyphs
    def outline(self, gid, depth=0):
        """[[(x, y, tag)]] in font units; composites resolved (transform applied, rounded)."""
        go, _ = self.t['glyf']
        a, b = self.loca[gid], self.loca[gid + 1]
        if a == b:
            return []
        p = go + a
        nc, = struct.unpack_from('>h', self.d, p)
        p += 10
        if nc >= 0:
            return self._simple(p, nc)
        res = []
        while True:
            fl, cg = struct.unpack_from('>HH', self.d, p)
            p += 4
            if fl & 1:
                e, f = struct.unpack_from('>hh', self.d, p); p += 4
            else:
                e, f = struct.unpack_from('>bb', self.d, p); p += 2
            m = (1.0, 0.0, 0.0, 1.0)
            if fl & 8:
                s = struct.unpack_from('>h', self.d, p)[0] / 16384; p += 2; m = (s, 0.0, 0.0, s)
            elif fl & 0x40:
                x, y = struct.unpack_from('>hh', self.d, p); p += 4; m = (x / 16384, 0.0, 0.0, y / 16384)
            elif fl & 0x80:
                q = struct.unpack_from('>hhhh', self.d, p); p += 8; m = tuple(v / 16384 for v in q)
            if not fl & 2:
                raise ValueError('point-matching composites are not supported')
            if depth < 8:
                for con in self.outline(cg, depth + 1):
                    res.append([(round(m[0] * x + m[2] * y + e), round(m[1] * x + m[3] * y + f), t) for x, y, t in con])
            if not fl & 0x20:
                break
        return res

    def _simple(self, p, nc):
        d = self.d
        ends = struct.unpack_from('>%dH' % nc, d, p)
        p += 2 * nc
        il, = struct.unpack_from('>H', d, p)
        p += 2 + il
        n = ends[-1] + 1 if nc else 0
        flags = []
        while len(flags) < n:
            f = d[p]; p += 1
            flags.append(f)
            if f & 8:
                r = d[p]; p += 1
                flags += [f] * r
        xs, x = [], 0
        for f in flags:
            if f & 2:
                v = d[p]; p += 1
                x += v if f & 0x10 else -v
            elif not f & 0x10:
                x += struct.unpack_from('>h', d, p)[0]; p += 2
            xs.append(x)
        ys, y = [], 0
        for f in flags:
            if f & 4:
                v = d[p]; p += 1
                y += v if f & 0x20 else -v
            elif not f & 0x20:
                y += struct.unpack_from('>h', d, p)[0]; p += 2
            ys.append(y)
        out, s = [], 0
        for e in ends:
            out.append([(xs[i], ys[i], 1 if flags[i] & 1 else 0) for i in range(s, e + 1)])
            s = e + 1
        return out


if __name__ == '__main__':
    data = open(sys.argv[1], 'rb').read()
    n = TTF(data).faces
    for i in range(n) if len(sys.argv) < 3 else [int(sys.argv[2])]:
        f = TTF(data, i)
        print(i, repr(f.name), 'upem', f.upem, 'glyphs', f.n_glyphs, 'chars', len(f.cmap),
              'ascent/descent', f.ascent, f.descent, 'cyrillic' if 0x0436 in f.cmap else '')
