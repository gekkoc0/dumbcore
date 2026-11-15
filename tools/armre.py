#!/usr/bin/env python3
"""Tiny reverse-engineering helper for the MOCOR code images (needs capstone: work/.venv).

    from armre import Image
    k = Image('work/ext/<build>/EXEC_KERNEL_IMAGE.bin', 0x80a06000)
    k.find_str('IMG_DEC')            -> [(addr, text)]
    k.xrefs(addr)                    -> [addr of LDR instructions that load addr]
    k.func_start(addr)               -> guess of function start (push {.., lr})
    k.dump(start, n)                 -> print Thumb disassembly
"""
import re, struct, bisect
import capstone as cs

HDR = 0x200  # DHTB header


class Image:
    def __init__(self, path, base):
        self.d = open(path, 'rb').read()[HDR:]
        self.base = base
        self.md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
        self.md.detail = True
        self._pools = None

    def off(self, a):
        return a - self.base

    def u32(self, a):
        return struct.unpack_from('<I', self.d, self.off(a))[0]

    def cstr(self, a):
        o = self.off(a)
        return self.d[o:self.d.index(b'\0', o)].decode('latin-1')

    def find_str(self, pat):
        rx = re.compile(pat.encode() if isinstance(pat, str) else pat)
        out = []
        for m in re.finditer(rb'[\x20-\x7e\t\r\n]{4,}\x00', self.d):
            if rx.search(m.group()):
                out.append((self.base + m.start(), m.group()[:-1].decode('latin-1')))
        return out

    def pools(self):
        """value -> list of addresses (4-aligned) where that 32-bit word is stored."""
        if self._pools is None:
            self._pools = {}
            for i in range(0, len(self.d) - 3, 4):
                v = struct.unpack_from('<I', self.d, i)[0]
                self._pools.setdefault(v, []).append(self.base + i)
        return self._pools

    def xrefs(self, target, window=4096):
        """find Thumb LDR rX,[pc,#imm] instructions loading a literal equal to target
        (also target|1 for function pointers)."""
        res = []
        for val in (target, target | 1):
            for pa in self.pools().get(val, []):
                lo = max(self.base, pa - window)
                # scan 2-byte aligned candidates for 16-bit and 32-bit LDR literal encodings
                for a in range(lo & ~1, pa, 2):
                    o = self.off(a)
                    hw = struct.unpack_from('<H', self.d, o)[0]
                    if hw >> 11 == 0b01001:  # LDR Rt,[PC,#imm8*4] (16-bit)
                        lit = ((a + 4) & ~3) + (hw & 0xff) * 4
                        if lit == pa:
                            res.append(a)
                    elif hw & 0xff7f == 0xf85f and o + 4 <= len(self.d):  # LDR.W Rt,[PC,#+-imm12]
                        hw2 = struct.unpack_from('<H', self.d, o + 2)[0]
                        imm = hw2 & 0xfff
                        lit = ((a + 4) & ~3) + (imm if hw & 0x80 else -imm)
                        if lit == pa:
                            res.append(a)
        return sorted(set(res))

    def adr_refs(self, target, window=4096):
        """find ADR Rd, label (16-bit and 32-bit ADDW/SUBW Rd, PC, #imm) pointing at target."""
        res = []
        lo = max(self.base, target - window - 4)
        hi = min(self.base + len(self.d) - 4, target + window)
        for a in range(lo & ~1, hi, 2):
            o = self.off(a)
            hw = struct.unpack_from('<H', self.d, o)[0]
            pcal = (a + 4) & ~3
            if hw >> 11 == 0b10100 and pcal + (hw & 0xff) * 4 == target:
                res.append(a)
            elif hw & 0xfbff in (0xf20f, 0xf2af):
                hw2 = struct.unpack_from('<H', self.d, o + 2)[0]
                imm = ((hw >> 10) & 1) << 11 | ((hw2 >> 12) & 7) << 8 | (hw2 & 0xff)
                if (pcal + imm if hw & 0xfbff == 0xf20f else pcal - imm) == target:
                    res.append(a)
        return res

    def bl_targets_to(self, target, lo=None, hi=None):
        """find BL instructions calling target (scan whole image, slow-ish)."""
        out = []
        d = self.d
        lo = self.off(lo) if lo else 0
        hi = self.off(hi) if hi else len(d) - 4
        for o in range(lo & ~1, hi, 2):
            h1, h2 = struct.unpack_from('<HH', d, o)
            if (h1 & 0xf800) == 0xf000 and (h2 & 0xd000) in (0xd000, 0xc000):
                s = (h1 >> 10) & 1
                j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
                i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
                imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
                if s:
                    imm -= 1 << 25
                a = self.base + o
                t = a + 4 + imm
                if (h2 & 0xd000) == 0xc000:  # BLX -> ARM, align
                    t &= ~3
                if t == target & ~1:
                    out.append(a)
        return out

    def func_start(self, a, limit=0x2000):
        """walk back to the nearest PUSH {...,lr} (16-bit B5xx or 32-bit E92D 4xxx)."""
        o = self.off(a) & ~1
        for k in range(o, max(0, o - limit), -2):
            hw = struct.unpack_from('<H', self.d, k)[0]
            if hw & 0xff00 == 0xb500:
                return self.base + k
            if hw == 0xe92d and struct.unpack_from('<H', self.d, k + 2)[0] & 0x4000:
                return self.base + k
        return None

    def dis(self, start, size=0x200):
        o = self.off(start)
        return list(self.md.disasm(self.d[o:o + size], start))

    def dump(self, start, size=0x200, annotate=True):
        for ins in self.dis(start, size):
            note = ''
            if annotate and ins.mnemonic.startswith('ldr') and '[pc' in ins.op_str:
                try:
                    lit = ((ins.address + 4) & ~3) + ins.operands[1].mem.disp
                    v = self.u32(lit)
                    note = f'   ; ={v:#x}'
                    if self.base <= v < self.base + len(self.d):
                        try:
                            sv = self.cstr(v)
                            if 3 < len(sv) < 120 and sv.isprintable():
                                note += f' "{sv}"'
                        except ValueError:
                            pass
                except Exception:
                    pass
            print(f'{ins.address:#010x}: {ins.mnemonic:<8} {ins.op_str}{note}')
