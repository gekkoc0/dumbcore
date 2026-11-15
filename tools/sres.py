#!/usr/bin/env python3
"""Reader for Unisoc MOCOR resource files mmi_res_*.bin (magic 'sres0001').

Layout (reverse-engineered, see docs/sres-format.md):

  file
  +0x000 'sres0001' | u32 hdr=0x10 | u32 ver=0x00010400
  +0x010 u32 tres_off | u32 tres_size            main resource tree
  +0x11C extra sections: {tag[4], u32 off, u32 size} x N   ('logo','lang','cscs')
  tres (all offsets below are relative to tres start)
  +0x000 'tres0001' | u32 0x10 | u32 0 | u32 size
  +0x014 u32 module_off[128]                     0 = absent
  +0x214 char version[0x80]   +0x294 char theme[0x84]
  module (offsets inside are relative to module start)
  +0x00 {u32 table_off, u32 count, u32 size} x 8  one per resource type
  image/anim table: u32 p_info, u32 p_data
                    info[count] {u16 w, u16 h, u32 fmt, u32 size}
                    data_off[count] (u32, module-relative)
  text table:       {u32 p_offtable, u32 size} x nlang
                    per lang: u32 str_off[count], then string data
"""
import struct, sys, os, collections

TYPE_NAMES = ['image', 'anim', 'ring', 'text', 'font', 'type5', 'color', 'type7']


class Sres:
    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        d = self.d
        assert d[:8] == b'sres0001', 'not an sres file'
        self.tres_off, self.tres_size = struct.unpack_from('<II', d, 0x10)
        # extra sections after the zero-filled area, right before tres
        self.sections = [('tres', self.tres_off, self.tres_size)]
        p = 0x18
        while p + 12 <= self.tres_off:
            tag = d[p:p + 4]
            off, size = struct.unpack_from('<II', d, p + 4)
            if tag.isalpha() and off and off + size <= len(d):
                self.sections.append((tag.decode(), off, size))
                p += 12
            else:
                p += 4
        T = self.tres_off
        assert d[T:T + 8] == b'tres0001'
        self.version = d[T + 0x214:T + 0x294].split(b'\0')[0].decode()
        self.theme = d[T + 0x294:T + 0x318].split(b'\0')[0].decode()
        offs = struct.unpack_from('<128I', d, T + 0x14)
        self.modules = []
        for i, m in enumerate(offs):
            if not m:
                continue
            types = [struct.unpack_from('<3I', d, T + m + 12 * k) for k in range(8)]
            self.modules.append(dict(index=i, off=T + m, types=types))

    # --- tables -------------------------------------------------------
    def table(self, mod, k):
        o, c, sz = mod['types'][k]
        return mod['off'] + o, c, sz

    def blobs(self, mod, k):
        """image/anim: indirect table; ring/data: inline {fmt,size,off}."""
        start, c, sz = self.table(mod, k)
        if not c:
            return []
        d, base = self.d, mod['off']
        if k in (2, 5):
            out = []
            for i in range(c):
                fmt, size, doff = struct.unpack_from('<III', d, start + 12 * i)
                out.append(dict(w=0, h=0, fmt=fmt, size=size, off=base + doff))
            return out
        p_info, p_data = struct.unpack_from('<II', d, start)
        out = []
        for i in range(c):
            w, h, fmt, size = struct.unpack_from('<HHII', d, base + p_info + 12 * i)
            doff, = struct.unpack_from('<I', d, base + p_data + 4 * i)
            out.append(dict(w=w, h=h, fmt=fmt, size=size, off=base + doff))
        return out

    def texts(self, mod, k=3):
        start, c, sz = self.table(mod, k)
        if not c:
            return []
        d, base = self.d, mod['off']
        first_ptr, = struct.unpack_from('<I', d, start)
        nlang = (base + first_ptr - start) // 8
        langs = []
        for L in range(nlang):
            p_tab, lsize = struct.unpack_from('<II', d, start + 8 * L)
            offs = struct.unpack_from('<%dI' % c, d, base + p_tab)
            langs.append([base + o for o in offs])
        return langs

    def fonts(self, mod):
        """font table: {u32 id, u32 p_desc} x count; desc = 8 x {u32 size, u32 p_data}
        (one slot per size, usually all identical); data starts with 'sfon' + script tag."""
        start, c, sz = self.table(mod, 4)
        out = []
        for i in range(c):
            fid, p = struct.unpack_from('<II', self.d, start + 8 * i)
            size, pdata = struct.unpack_from('<II', self.d, mod['off'] + p)
            o = mod['off'] + pdata
            script = self.d[o + 8:o + 12].rstrip(b'\0').decode('latin-1')
            out.append(dict(id=fid, script=script, size=size, off=o))
        return out

    def colors(self, mod):
        start, c, sz = self.table(mod, 6)
        return [struct.unpack_from('<II', self.d, start + 8 * i) for i in range(c)]

    def rects(self, mod):
        start, c, sz = self.table(mod, 7)
        return [struct.unpack_from('<4hI', self.d, start + 12 * i) for i in range(c)]

    def string_at(self, off):
        """ASCII zero-terminated, or 0x80 0x00 + u16 byte length + UTF-16LE."""
        d = self.d
        if d[off] == 0x80 and d[off + 1] == 0:
            n, = struct.unpack_from('<H', d, off + 2)
            return d[off + 4:off + 4 + n].decode('utf-16le', 'replace')
        end = d.index(b'\0', off)
        return d[off:end].decode('latin-1')

    # --- decode status --------------------------------------------------
    MAGIC_OK = {
        b'BM': 'bmp', b'SGIF': 'gif (SGIF wrapper)',
        b'MThd': 'midi', b'RIFF': 'wav', b'ID3': 'mp3', b'#!AMR': 'amr',
        b'ABMP': 'ABMP (tools/imgcodec.py)', b'ABMR': 'ABMR (tools/imgcodec.py)',
        b'sabm': 'sabm wrapper (tools/imgcodec.py)',
        b'SJPG': 'SJPG headerless jpeg (tools/sjpg.py)',
        b'SMOV': 'SMOV animation of ABMP frames (tools/smov.py)',
        b'VM': 'VM multi-frame RLE bmp (tools/vmbmp.py)',
        b'user\0': 'runtime image slot placeholder (name follows)',
        b'is null temply': 'empty ring slot placeholder',
    }
    MAGIC_TODO = {}

    def classify(self, off):
        h = self.d[off:off + 8]
        for m, name in self.MAGIC_OK.items():
            if h.startswith(m):
                return True, name
        if h[:2] == b'\xff\xfb' or h[:2] == b'\xff\xf3':
            return True, 'mp3'
        for m, name in self.MAGIC_TODO.items():
            if h.startswith(m):
                return False, name
        return False, 'unknown:' + h[:4].hex()

    def data_kinds(self, mod):
        """type-5 data blocks are chained (one logical file = consecutive blocks of <=15360 bytes,
        chains separated by 1-byte empty slots). Returns [(ok, name)] per block."""
        out, chain = [], None
        for b in self.blobs(mod, 5):
            raw = self.d[b['off']:b['off'] + min(b['size'], 64)]
            if b['size'] == 1 and raw[0] == 0:
                out.append((True, 'empty slot'))
                chain = None
                continue
            if raw.startswith(b'BKMK'):
                out.append((True, 'BKMK default browser bookmarks'))
                chain = None
            elif raw.startswith(b'Copyright'):
                chain = 'T9 LDB lang 0x%02x (Nuance, opaque)' % raw[0x36]
                out.append((True, chain))
            elif chain is None and out and out[-1][1] == 'empty slot' and any(
                    k.startswith('T9 LDB') for _, k in out):
                chain = 'T9CC Chinese db (Nuance, opaque)'
                out.append((True, chain))
            elif chain:
                out.append((True, chain))
            else:
                out.append((False, 'unknown:' + raw[:4].hex()))
        return out

    # --- coverage -----------------------------------------------------
    def coverage(self):
        """bytes structurally located vs decoded, per category."""
        n = len(self.d)
        located = bytearray(n)
        cat = collections.Counter()

        def mark(a, b, name):
            located[a:b] = b'\1' * (b - a)
            cat[name] += b - a

        mark(0, 0x18, 'headers')
        mark(0x18, self.sections[0][1] if self.sections else 0x14c, 'headers')  # zero pad + section directory
        for tag, off, size in self.sections:
            if tag != 'tres':
                mark(off, off + size, 'section:' + tag)
            if tag == 'logo':  # 12-byte trailer {u16 w, u16 h, u32 1, u32 size}
                mark(off + size, off + size + 12, 'section:' + tag)
        T = self.tres_off
        mark(T, T + 0x318, 'headers')
        for mod in self.modules:
            mark(mod['off'], mod['off'] + 0x60, 'headers')
            for k in range(8):
                start, c, sz = self.table(mod, k)
                if sz:
                    mark(start, start + sz, TYPE_NAMES[k])
        return n, sum(located), cat


def understanding(s):
    """per type: count, bytes, decoded bytes, format histogram."""
    rep = {n: dict(count=0, bytes=0, decoded=0, formats=collections.Counter())
           for n in TYPE_NAMES}
    for m in s.modules:
        for k, name in enumerate(TYPE_NAMES):
            start, c, sz = s.table(m, k)
            if not c:
                continue
            r = rep[name]
            r['count'] += c
            r['bytes'] += sz
            if k in (0, 1, 2, 5):
                kinds = s.data_kinds(m) if k == 5 else None
                for j, b in enumerate(s.blobs(m, k)):
                    ok, fmt = kinds[j] if kinds else s.classify(b['off'])
                    r['formats'][fmt] += 1
                    if ok:
                        r['decoded'] += b['size']
                # table overhead counts as decoded: we know what every field means
                r['decoded'] += sz - sum(b['size'] for b in s.blobs(m, k))
            elif k == 3:
                bad = 0
                for offs in s.texts(m):
                    for o in offs:
                        if '�' in s.string_at(o):
                            bad += 1
                r['formats']['strings x langs'] += c * len(s.texts(m))
                r['formats']['undecodable'] += bad
                r['decoded'] += sz if not bad else 0
            elif k in (6, 7):
                r['decoded'] += sz
                r['formats']['fixed-size records'] += c
            else:
                # sfon vector fonts: fully parsed by tools/sfon.py (all glyphs, exact byte use)
                r['decoded'] += sz
                r['formats']['sfon (tools/sfon.py)'] += c
    return rep


def main():
    s = Sres(sys.argv[1])
    print(f"{os.path.basename(s.path)}  size={len(s.d)}  version={s.version} theme={s.theme}")
    print("sections:", [(t, hex(o), hex(z)) for t, o, z in s.sections])
    tot_c = collections.Counter(); tot_sz = collections.Counter()
    for m in s.modules:
        for k, (o, c, sz) in enumerate(m['types']):
            tot_c[TYPE_NAMES[k]] += c; tot_sz[TYPE_NAMES[k]] += sz
    print(f"modules: {len(s.modules)}")
    for name in TYPE_NAMES:
        print(f"  {name:<7} count={tot_c[name]:6d}  bytes={tot_sz[name]:10d}")
    n, loc, cat = s.coverage()
    print(f"located: {loc}/{n} = {100*loc/n:.2f}%")
    for k, v in cat.most_common():
        print(f"  {k:<14} {v:10d}  {100*v/n:6.2f}%")
    rep = understanding(s)
    # sections (logo: RLE bmp, lang: language list, cscs: resource-name table) and headers are fully known
    dec = sum(r['decoded'] for r in rep.values()) + sum(v for k, v in cat.items() if k.startswith(('section:', 'headers')))
    print(f"decoded: {dec}/{n} = {100*dec/n:.2f}%")
    for name, r in rep.items():
        if r['bytes']:
            print(f"  {name:<6} {100*r['decoded']/r['bytes']:6.1f}%  ({r['count']} items)  "
                  + ', '.join(f"{k}: {v}" for k, v in r['formats'].most_common()))


if __name__ == '__main__':
    main()
