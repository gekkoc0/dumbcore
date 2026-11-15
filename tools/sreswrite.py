#!/usr/bin/env python3
"""Writer for mmi_res (sres0001): replace blobs and rebuild the file with all offsets fixed.

Layout rules measured on every stock build (work/sres_layout.py), see docs/sres-format.md:
  file   = header + section directory | tres | sections (logo, logo, lang, cscs, with logo trailers)
  tres   = header (module_off[128] tres-relative) | modules back to back
  module = 0x60 header {u32 table_off, u32 count, u32 size} x 8 (module-relative) | 8 tables back to back
  image/anim table: u32 p_info, u32 p_data | info[n] {u16 w, u16 h, u32 fmt, u32 size} | u32 data_off[n] | blobs
  ring/data table : {u32 fmt, u32 size, u32 off}[n] | blobs
  blobs in index order, each starts 4-aligned (module-relative); padding 0xAD (image), 0xBD (anim), 0xCD (ring/data);
  the table size is padded the same way.
All pointers inside a module are module-relative, so an unchanged table that moves is relocated by adding the shift
to its pointers (image/anim: p_info, p_data, data_off; ring/data: off; text: p_offtable, str_off; font: p_desc, p_data).

API:
    w = SresWriter('mmi_res.bin')
    w.set_blob(module, k, index, data, w=None, h=None, fmt=None)   # k: 0 image, 1 anim, 2 ring, 5 data
    open('out.bin', 'wb').write(w.build())

    sreswrite.py <in> <out>            # rebuild without changes (must be byte-identical)
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sres import Sres

PAD = {0: 0xAD, 1: 0xBD, 2: 0xCD, 5: 0xCD}   # filler bytes measured per table type


def _pad4(buf, pos_rel, byte):
    """append padding so that pos_rel + len(added) is a multiple of 4; return added length."""
    n = (-pos_rel) & 3
    buf += bytes([byte]) * n
    return n


class SresWriter:
    def __init__(self, path):
        self.s = Sres(path)
        self.d = self.s.d
        self.changes = {}   # (module_index, k, i) -> dict(data, w, h, fmt)

    # ------------------------------------------------------------------ edits
    def set_blob(self, module, k, i, data, w=None, h=None, fmt=None):
        assert k in (0, 1, 2, 5), 'only image/anim/ring/data blobs can be replaced'
        m = self._mod(module)
        assert 0 <= i < m['types'][k][1], 'index out of range'
        self.changes[(module, k, i)] = dict(data=bytes(data), w=w, h=h, fmt=fmt)

    def set_font(self, module, i, data):
        """replace font i of the module's font table (type 4) with a new sfon file."""
        m = self._mod(module)
        assert 0 <= i < m['types'][4][1], 'font index out of range'
        assert bytes(data[:4]) == b'sfon', 'not an sfon font'
        self.changes[(module, 4, i)] = dict(data=bytes(data), w=None, h=None, fmt=None)

    def _build_font_table(self, m, new_start_rel):
        """font table: {u32 id, u32 p_desc}[n] | descs: S x {u32 size, u32 p_data} per font (S = 7, 8 or 11 slots
        depending on the build; every slot of a font points to the same data) | font files, 4-aligned, filler 0xDD."""
        s, d = self.s, self.d
        start, c, sz = s.table(m, 4)
        base, rel = m['off'], start - m['off']
        ptrs = []          # (position of the u32 p_data in the table, old p_data, font index)
        descs = [struct.unpack_from('<II', d, start + 8 * i)[1] for i in range(c)]
        data_start = None
        for i, pd in enumerate(descs):
            j = 0
            while True:
                at = pd + 8 * j
                if data_start is not None and at >= data_start:
                    break
                size, p = struct.unpack_from('<II', d, base + at)
                if p:
                    ptrs.append((at, p, i))
                    data_start = p if data_start is None else min(data_start, p)
                j += 1
                if j > 64:
                    raise ValueError('font descriptor not understood')
        old_blobs = sorted({p for _, p, _ in ptrs})
        size_of = {}
        for at, p, i in ptrs:
            size_of[p] = struct.unpack_from('<I', d, base + at)[0]
        owner = {p: i for _, p, i in ptrs}
        head = bytearray(d[start:base + data_start])
        delta = new_start_rel - rel
        for i in range(c):
            v, = struct.unpack_from('<I', head, 8 * i + 4)
            struct.pack_into('<I', head, 8 * i + 4, v + delta)
        area, new_p, new_size = bytearray(), {}, {}
        pos0 = new_start_rel + len(head)
        for p in old_blobs:
            ch = self.changes.get((m['index'], 4, owner[p]))
            blob = ch['data'] if ch else d[base + p:base + p + size_of[p]]
            new_p[p] = pos0 + len(area)
            new_size[p] = len(blob)
            area += blob
            _pad4(area, pos0 + len(area), 0xDD)
        for at, p, i in ptrs:
            o = at - rel
            struct.pack_into('<II', head, o, new_size[p], new_p[p])
        return bytes(head + area)

    def set_text(self, module, i, lang, text):
        """replace string i of language lang (index in the module's text table) with a Python str."""
        m = self._mod(module)
        assert 0 <= i < m['types'][3][1], 'string index out of range'
        self.changes[(module, 3, (i, lang))] = dict(data=text, w=None, h=None, fmt=None)

    def set_color(self, module, i, rgb565, flag=None):
        """replace color i ({u32 rgb565, u32 flag}) of the module's color table (type 6)."""
        m = self._mod(module)
        assert 0 <= i < m['types'][6][1], 'color index out of range'
        self.changes[(module, 6, i)] = dict(data=(rgb565, flag), w=None, h=None, fmt=None)

    @staticmethod
    def encode_string(text):
        """stock rule: all code points < 0x100 -> Latin-1 bytes + zero terminator, otherwise 0x80 0x00 +
        u16 byte length + UTF-16LE without terminator."""
        if all(ord(ch) < 0x100 for ch in text):
            return text.encode('latin-1') + b'\0'
        u = text.encode('utf-16-le')
        return b'\x80\x00' + struct.pack('<H', len(u)) + u

    def _build_text_table(self, m, new_start_rel):
        """text table: {u32 p_tab, u32 words}[nlang] | u32 str_off[n] per language (all tables first) | strings:
        language by language, in index order, identical strings stored once per language, each padded with zeros to
        4 bytes; 'words' = bytes of that language's strings incl. padding / 4."""
        s, d = self.s, self.d
        start, c, sz = s.table(m, 3)
        langs = s.texts(m)
        nlang = len(langs)
        texts = [[s.string_at(o) for o in langs[L]] for L in range(nlang)]
        for key, ch in self.changes.items():
            if key[0] == m['index'] and key[1] == 3:
                i, L = key[2]
                texts[L][i] = ch['data']
        pos = new_start_rel + 8 * nlang + 4 * c * nlang
        heap, tabs, words = bytearray(), [], []
        for L in range(nlang):
            seen, offs, before = {}, [], len(heap)
            for t in texts[L]:
                b = self.encode_string(t)
                if b not in seen:
                    seen[b] = pos + len(heap)
                    heap += b
                    heap += b'\0' * (-len(heap) & 3)
                offs.append(seen[b])
            tabs.append(offs)
            words.append((len(heap) - before) // 4)
        out = bytearray()
        for L in range(nlang):
            out += struct.pack('<II', new_start_rel + 8 * nlang + 4 * c * L, words[L])
        for L in range(nlang):
            out += struct.pack('<%dI' % c, *tabs[L])
        return bytes(out + heap)

    def _mod(self, index):
        for m in self.s.modules:
            if m['index'] == index:
                return m
        raise KeyError(index)

    # ------------------------------------------------------------ table build
    def _build_blob_table(self, m, k, new_start_rel):
        """rebuild image/anim/ring/data table at module-relative position new_start_rel."""
        s, d = self.s, self.d
        start, c, sz = s.table(m, k)
        bl = s.blobs(m, k)
        items = []
        for i, b in enumerate(bl):
            ch = self.changes.get((m['index'], k, i))
            data = ch['data'] if ch else d[b['off']:b['off'] + b['size']]
            w = ch['w'] if ch and ch['w'] is not None else b['w']
            h = ch['h'] if ch and ch['h'] is not None else b['h']
            fmt = ch['fmt'] if ch and ch['fmt'] is not None else b['fmt']
            items.append((w, h, fmt, data))
        out = bytearray()
        if k in (0, 1):
            hdr_len = 8 + 16 * c
        else:
            hdr_len = 12 * c
        blob_area = bytearray()
        offs = []
        pos = new_start_rel + hdr_len
        for (w, h, fmt, data) in items:
            offs.append(pos + len(blob_area))
            blob_area += data
            _pad4(blob_area, pos + len(blob_area), PAD[k])
        if k in (0, 1):
            p_info = new_start_rel + 8
            p_data = p_info + 12 * c
            out += struct.pack('<II', p_info, p_data)
            for (w, h, fmt, data) in items:
                out += struct.pack('<HHII', w, h, fmt, len(data))
            out += struct.pack('<%dI' % c, *offs)
        else:
            for (w, h, fmt, data), o in zip(items, offs):
                out += struct.pack('<III', fmt, len(data), o)
        out += blob_area
        return bytes(out)

    def _relocate(self, m, k, delta):
        """raw copy of an unchanged table with its module-relative pointers shifted by delta."""
        s, d = self.s, self.d
        start, c, sz = s.table(m, k)
        t = bytearray(d[start:start + sz])
        if not delta or not c:
            return bytes(t)
        rel = start - m['off']                      # old module-relative start of the table

        def fix(at_rel_old):                        # u32 pointer stored at old module-relative position
            p = at_rel_old - rel
            v, = struct.unpack_from('<I', t, p)
            struct.pack_into('<I', t, p, v + delta)

        if k in (0, 1):
            p_info, p_data = struct.unpack_from('<II', t, 0)
            fix(rel), fix(rel + 4)
            for i in range(c):
                fix(p_data + 4 * i)
        elif k in (2, 5):
            for i in range(c):
                fix(rel + 12 * i + 8)
        elif k == 3:
            first_ptr, = struct.unpack_from('<I', t, 0)
            nlang = (first_ptr - rel) // 8
            for L in range(nlang):
                p_tab, = struct.unpack_from('<I', t, 8 * L)
                fix(rel + 8 * L)
                for i in range(c):
                    fix(p_tab + 4 * i)
        elif k == 4:
            descs = set()
            for i in range(c):
                fid, p_desc = struct.unpack_from('<II', t, 8 * i)
                fix(rel + 8 * i + 4)
                descs.add(p_desc)
            for p_desc in descs:
                for j in range(8):
                    size, p_data = struct.unpack_from('<II', t, p_desc - rel + 8 * j)
                    if p_data:
                        fix(p_desc + 8 * j + 4)
        # 6 color, 7 rect: no pointers
        return bytes(t)

    def _build_module(self, m):
        s = self.s
        out = bytearray(0x60)
        hdr = []
        pos = old_pos = 0x60
        for k in range(8):
            o, c, sz = m['types'][k]
            if o != old_pos:
                raise ValueError(f"module {m['index']}: tables are not back to back "
                                 "(file was edited by another tool, e.g. ResOver) - not supported")
            touched = any(key[0] == m['index'] and key[1] == k for key in self.changes)
            if touched and k == 4:
                t = self._build_font_table(m, pos)
            elif touched and k == 3:
                t = self._build_text_table(m, pos)
            elif touched and k == 6:
                t = bytearray(self.d[self.s.table(m, 6)[0]:self.s.table(m, 6)[0] + sz])
                for key, ch in self.changes.items():
                    if key[0] == m['index'] and key[1] == 6:
                        rgb, flag = ch['data']
                        old_flag = struct.unpack_from('<I', t, 8 * key[2] + 4)[0]
                        struct.pack_into('<II', t, 8 * key[2], rgb, old_flag if flag is None else flag)
                t = bytes(t)
            elif touched:
                t = self._build_blob_table(m, k, pos)
            else:
                t = self._relocate(m, k, pos - o)
            hdr.append((pos, c, len(t)))
            out += t
            pos += len(t)
            old_pos += sz
        for k, (o, c, sz) in enumerate(hdr):
            struct.pack_into('<III', out, 12 * k, o, c, sz)
        return bytes(out)

    # ------------------------------------------------------------- whole file
    def build(self):
        s, d = self.s, self.d
        T, Tsize = s.tres_off, s.tres_size
        mods = sorted(s.modules, key=lambda m: m['off'])
        first_mod = mods[0]['off'] - T
        tres = bytearray(d[T:T + first_mod])        # tres header incl. module_off[128]
        new_off = {}
        for m in mods:
            new_off[m['index']] = len(tres)
            tres += self._build_module(m)
        for idx, o in new_off.items():
            struct.pack_into('<I', tres, 0x14 + 4 * idx, o)
        struct.pack_into('<I', tres, 0x10, len(tres))    # tres header: magic, u32 0x10, u32 0, u32 size
        delta = len(tres) - Tsize
        out = bytearray(d[:T]) + tres + d[T + Tsize:]
        struct.pack_into('<I', out, 0x14, len(tres))
        # section directory (0x18..tres): {tag[4], u32 off, u32 size}; shift sections that follow tres
        p = 0x18
        while p + 12 <= T:
            tag = d[p:p + 4]
            off, size = struct.unpack_from('<II', d, p + 4)
            if tag.isalpha() and off:
                if off >= T + Tsize:
                    struct.pack_into('<I', out, p + 4, off + delta)
                p += 12
            else:
                p += 4
        return bytes(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    data = SresWriter(src).build()
    open(dst, 'wb').write(data)
    same = data == open(src, 'rb').read()
    print(f'{len(data)} bytes ->', dst, '| identical to input' if same else '| DIFFERS from input')
