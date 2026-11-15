#!/usr/bin/env python3
"""UMS9117 (T107/T117) firmware helper — Python port of ideas from fphelper_t117
(github.com/ilyakurdyukov/spreadtrum_flash, public domain), adapted to our .pac partitions.

    t117fw.py kernel <EXEC_KERNEL_IMAGE.bin> [outdir]  # init (scatter-load) table, lzdec unpack, pinmap, keymap
    t117fw.py user   <EXEC_USER_IMAGE.bin>  [base]     # dial (service) codes table
    t117fw.py nv     <..._nvitem_....bin>              # NV item list (nv1 format)
"""
import struct, sys, os

KEYS = {0x01: 'DIAL', 0x04: 'UP', 0x05: 'DOWN', 0x06: 'LEFT', 0x07: 'RIGHT', 0x08: 'LSOFT', 0x09: 'RSOFT',
        0x0d: 'CENTER', 0x0e: 'CAMERA', 0x23: 'HASH', 0x24: 'VOLUP', 0x25: 'VOLDOWN', 0x2a: 'STAR',
        0x2b: 'PLUS', 0x2d: 'MINUS', **{0x30 + i: str(i) for i in range(10)}}


def u32s(b, o, n=1):
    return struct.unpack_from('<%dI' % n, b, o)


# ---------------- decompressors (Unisoc "lzdec2"/"lzdec3") ----------------
def lzdec3(src, pos, dst_size):
    out = bytearray(); s = pos
    while len(out) < dst_size:
        code = src[s]; s += 1
        skip = code & 7
        if not skip:
            skip = src[s]; s += 1
            if not skip: break
        ln = code >> 4
        if not ln:
            ln = src[s]; s += 1
        for _ in range(skip - 1):
            out.append(src[s]); s += 1
        if code & 8:
            ln += 1
            dist = src[s]; s += 1
            for _ in range(ln + 1):
                out.append(out[-dist])
        else:
            out.extend(b'\0' * ln)
    return bytes(out[:dst_size]), s - pos


def lzdec2(src, pos, dst_size):
    out = bytearray(); s = pos
    while len(out) < dst_size:
        code = src[s]; s += 1
        skip = code & 3
        if not skip:
            skip = src[s]; s += 1
            if not skip: break
        ln = code >> 4
        if not ln:
            ln = src[s]; s += 1
        for _ in range(skip - 1):
            out.append(src[s]); s += 1
        if ln:
            dist = src[s]; s += 1
            t = code >> 2 & 3
            if t == 3:
                t = src[s]; s += 1
            dist |= t << 8
            ln += 1
            for _ in range(ln + 1):
                out.append(out[-dist])
    return bytes(out[:dst_size]), s - pos


# ---------------- kernel: init table ----------------
SIG_INIT = struct.pack('<5I', 0xe8ba0e09, 0xf013000f, 0xbf180f01, 0xf0431afb, 0x47180301)
SIG_LZ3 = struct.pack('<4I', 0xf04f440a, 0xf8100c00, 0xf0133b01, 0xbf080407)
SIG_LZ2 = struct.pack('<4I', 0x3b01f810, 0xf013440a, 0xbf080403, 0x4b01f810)


def scan_kernel(path, outdir=None):
    raw = open(path, 'rb').read()
    b = raw[0x200:] if raw[:4] == b'DHTB' else raw
    res = dict(init_tables=[], segments=[], pinmap=None, keymap=None)
    i = b.find(SIG_INIT)
    while i >= 0:
        o1 = i + 0x14
        o2, o3 = u32s(b, o1, 2)
        o2 += o1; o3 += o1
        p = o1 + 8
        fns = {}
        lz = None
        if b[p:p + 16] == SIG_LZ3:
            lz = (3, p); p += 0x5c
        elif b[p:p + 16] == SIG_LZ2:
            lz = (2, p); p += 0x64
        if lz: fns['lzdec%d' % lz[0]] = lz[1]
        if u32s(b, p)[0] == 0xbf243a10:
            fns['copy'] = p; p += 0x1c
        if u32s(b, p)[0] == 0x24002300:
            fns['zero'] = p; p += 0x1c
        fns['nop'] = o1 - 0x1e
        n = (o3 - o2) // 16
        ents = [u32s(b, o2 + 16 * k, 4) for k in range(n)]
        # image base: the value that makes every fn pointer hit one of the known stubs
        base = None
        for name, off in fns.items():
            cand = (ents[0][3] & ~1) - off
            if all((e[3] & ~1) - cand in fns.values() for e in ents):
                base = cand; break
        tab = dict(at=o1, entries=[], base=base, fns={k: hex(v) for k, v in fns.items()})
        for src, dst, ln, fn in ents:
            kind = next((k for k, v in fns.items() if base is not None and (fn & ~1) - base == v), '?')
            tab['entries'].append(dict(src=src, dst=dst, len=ln, fn=kind))
        res['init_tables'].append(tab)
        i = b.find(SIG_INIT, i + 4)
    # unpack segments
    for tab in res['init_tables']:
        base = tab['base']
        if base is None: continue
        for e in tab['entries']:
            if e['fn'] not in ('copy', 'lzdec2', 'lzdec3'): continue
            off = e['src'] - base
            if not 0 <= off < len(b): continue
            if e['fn'] == 'copy':
                data, used = b[off:off + e['len']], e['len']
            else:
                data, used = (lzdec2 if e['fn'] == 'lzdec2' else lzdec3)(b, off, e['len'])
            seg = dict(dst=e['dst'], len=e['len'], fn=e['fn'], file_off=off, packed=used, ok=len(data) == e['len'])
            res['segments'].append(seg)
            if outdir:
                os.makedirs(outdir, exist_ok=True)
                open(os.path.join(outdir, 'seg_%08x_%s.bin' % (e['dst'], e['fn'])), 'wb').write(data)
    # pinmap: pairs {addr,val} with addr in PIN (0x402a0xxx) / ANA pin (0x40608xxx), ends with ~0,~0
    for i in range(0, len(b) - 32, 4):
        a0, _, a1, _, a2, _ = u32s(b, i, 6)
        if (a0 >> 12) == 0x402a0 and (a1 >> 12) == 0x402a0 and (a2 >> 12) == 0x402a0:
            j = i
            while j + 8 <= len(b):
                a, v = u32s(b, j, 2)
                if a == 0xffffffff and v == 0xffffffff:
                    res['pinmap'] = dict(off=i, end=j + 8, n=(j - i) // 8,
                                         lcd_pins=[_pin(b, i, 0x402a00b8 + 4 * k) for k in range(5)])
                    if outdir: open(os.path.join(outdir, 'pinmap.bin'), 'wb').write(b[i:j + 8])
                    break
                if (a >> 12) not in (0x402a0, 0x40608): break
                j += 8
            if res['pinmap']: break
    return res, b


def _pin(b, start, addr):
    j = start
    while True:
        a, v = u32s(b, j, 2)
        if a == 0xffffffff: return None
        if a == addr: return v
        j += 8


def find_keymap(blobs):
    """keymap = 8x8 u16 table of key codes (0xffff empty), as in check_keymap()."""
    hits = []
    for name, b in blobs:
        for i in range(0, len(b) - 128, 2):
            s = struct.unpack_from('<64H', b, i)
            if s.count(0xffff) < 20: continue
            vals = [x for x in s if x != 0xffff]
            if len(vals) < 15 or any(not (1 <= x <= 0x39) and x != 0x68 for x in vals): continue
            if not {0x30, 0x31, 0x39, 0x2a, 0x23} <= set(vals): continue
            if any(s[r * 8 + 6] != 0xffff or s[r * 8 + 7] != 0xffff for r in range(8)): continue
            hits.append((name, i, s))
    return hits


# ---------------- user: dial codes ----------------
def is_dial(b, o):
    if o >= len(b) or b[o] not in b'#*': return 0
    e = b.find(b'\0', o, o + 80)
    if e < 0: return 0
    s = b[o:e]
    return len(s) if all(c in b'#*0123456789' for c in s) else 0


def scan_user(path, base=0x88000000):
    raw = open(path, 'rb').read()
    b = raw[0x200:] if raw[:4] == b'DHTB' else raw
    n = len(b)
    out = []
    i = 0
    while i < n - 16:
        code, id1, id2, fn = u32s(b, i, 4)
        c = code - base
        if 0 <= c < n and 0 <= fn - base < n and id2 in (5, 0xb) and 1 <= id1 <= 10 and is_dial(b, c):
            # walk back and forward through 16-byte records
            s = i
            while s >= 16:
                cc, a1, a2, f = u32s(b, s - 16, 4)
                if not (0 <= cc - base < n and 1 <= a1 <= 64 and 1 <= a2 <= 64 and 0 <= f - base < n
                        and is_dial(b, cc - base) >= 3): break
                s -= 16
            e = i
            while e + 16 <= n:
                cc, a1, a2, f = u32s(b, e, 4)
                if not (0 <= cc - base < n and 1 <= a1 <= 64 and 1 <= a2 <= 64 and 0 <= f - base < n
                        and is_dial(b, cc - base) >= 1): break
                e += 16
            for o in range(s, e, 16):
                cc, a1, a2, f = u32s(b, o, 4)
                z = b.index(b'\0', cc - base)
                out.append(dict(code=b[cc - base:z].decode(), group=a2, item=a1, handler=hex(f)))
            i = e
            continue
        i += 4
    return out


# ---------------- NV ----------------
def nv_items(path):
    b = open(path, 'rb').read()
    nvid = u32s(b, 0)[0]
    i, last, items = 4, 0, []
    while i + 4 <= len(b):
        iid, n = struct.unpack_from('<HH', b, i)
        if (iid & n) == 0xffff:
            return nvid, items, i + 4, len(b)
        if iid <= last: break
        last = iid
        items.append((iid, n, i + 4))
        i += 4 + ((n + 3) & ~3)
    return nvid, items, i, len(b)


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == 'kernel':
        outdir = sys.argv[3] if len(sys.argv) > 3 else None
        res, b = scan_kernel(path, outdir)
        for t in res['init_tables']:
            print(f"init table @0x{t['at']:x}, image base {hex(t['base']) if t['base'] is not None else '?'}, stubs {t['fns']}")
            for e in t['entries']:
                print(f"   {e['fn']:<7} src 0x{e['src']:08x} -> dst 0x{e['dst']:08x}  len 0x{e['len']:x}")
        for s in res['segments']:
            print(f"segment dst 0x{s['dst']:08x} len 0x{s['len']:x} via {s['fn']} from file+0x{s['file_off']:x} "
                  f"(packed 0x{s['packed']:x}) {'ok' if s['ok'] else 'SHORT'}")
        pm = res['pinmap']
        if pm:
            print(f"pinmap @0x{pm['off']:x}..0x{pm['end']:x}: {pm['n']} entries; LCD pins (SPI0 CSN,DO,DI,CLK,CD) = "
                  + ', '.join('-' if v is None else hex(v) for v in pm['lcd_pins']))
        blobs = [('kernel', b)]
        if outdir:
            for f in sorted(os.listdir(outdir)):
                if f.startswith('seg_'): blobs.append((f, open(os.path.join(outdir, f), 'rb').read()))
        for name, off, s in find_keymap(blobs)[:3]:
            print(f"keymap candidate in {name} @0x{off:x}: boot key = {KEYS.get(s[0], hex(s[0]))}, "
                  f"bl_update keys = {KEYS.get(s[1], hex(s[1]))}, {KEYS.get(s[8], hex(s[8]))}")
            for r in range(8):
                row = s[r * 8:r * 8 + 8]
                if any(x != 0xffff for x in row):
                    print('     ' + ' '.join(f"{KEYS.get(x, '.' if x == 0xffff else hex(x)):>7}" for x in row))
    elif cmd == 'user':
        base = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x88000000
        for d in scan_user(path, base):
            print(f"  {d['code']:<16} group {d['group']:>2} item {d['item']:>2}  handler {d['handler']}")
    elif cmd == 'nv':
        nvid, items, end, size = nv_items(path)
        print(f"nv id 0x{nvid:08x}, {len(items)} items, parsed up to 0x{end:x} of 0x{size:x}")
        for iid, n, off in items[:12]:
            print(f"   id {iid:5d} size {n:6d} @0x{off:x}")


if __name__ == '__main__':
    main()
