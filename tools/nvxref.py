#!/usr/bin/env python3
"""Cross-reference NV item ids with the code that uses them.

For every Thumb BL/BLX in a code image, look at up to 8 preceding instructions for an immediate loaded
into r0 (movs/mov.w/movw r0,#imm, or ldr r0,=imm from a literal pool). Call targets whose r0 immediates
overlap the NV id set most are the NV read/write functions; every such call site gives (nv id -> caller).
Callers are mapped to source files via work/ghidra/<img>_modmap.json (tools/modmap.py).

    nvxref.py <nvitem.bin> [out.json]
Needs capstone (work/.venv).
"""
import json, struct, sys, collections, bisect
from array import array
import capstone as cs

sys.path.insert(0, __import__('os').path.dirname(__file__))
from t117fw import nv_items

ROOT = __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
B = ROOT + '/work/ext/official_3210_11.00.17.00_QB_16ICN18HK00/'
IMAGES = (('kernel', B + 'EXEC_KERNEL_IMAGE.bin', 0x80a06000),
          ('user', B + 'EXEC_USER_IMAGE.bin', 0x88000000))


def bl_sites(d, base):
    hw = array('H', d[:len(d) & ~1])
    for i in range(len(hw) - 1):
        h1, h2 = hw[i], hw[i + 1]
        if h1 & 0xf800 != 0xf000 or h2 & 0xc000 != 0xc000:
            continue
        s = (h1 >> 10) & 1
        j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
        imm = (s << 24) | ((1 - (j1 ^ s)) << 23) | ((1 - (j2 ^ s)) << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
        if s:
            imm -= 1 << 25
        a = base + 2 * i
        t = a + 4 + imm
        if not h2 & 0x1000:  # BLX -> ARM target, word aligned
            t &= ~3
        yield a, t


def r0_imm(md, d, base, site):
    """immediate in r0 set by the instructions right before site (None if not found / overwritten)."""
    lo = max(0, site - base - 24)
    best = None
    for start in (lo, lo + 2):
        val = None
        for ins in md.disasm(d[start:site - base], base + start):
            ops = ins.op_str.replace(' ', '')
            if ops.startswith('r0,'):
                rest = ops[3:]
                if ins.mnemonic in ('movs', 'mov', 'mov.w', 'movw', 'movs.w') and rest.startswith('#'):
                    try:
                        val = int(rest[1:], 0)
                    except ValueError:
                        val = None
                elif ins.mnemonic.startswith('ldr') and '[pc' in ops:
                    try:
                        lit = ((ins.address + 4) & ~3) + int(ops.split('#')[-1].rstrip(']'), 0)
                        val = struct.unpack_from('<I', d, lit - base)[0]
                    except Exception:
                        val = None
                else:
                    val = None  # r0 overwritten by something else
        if val is not None:
            best = val
    return best


def veneer_target(d, base, t):
    """user image calls kernel via 'ldr pc,[pc,#-4]; .word target' veneers."""
    o = t - base
    if 0 <= o < len(d) - 8 and struct.unpack_from('<I', d, o)[0] == 0xe51ff004:
        return struct.unpack_from('<I', d, o + 4)[0] & ~1
    return t


def main():
    nvpath = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    _, items, _, _ = nv_items(nvpath)
    ids = {iid for iid, _, _ in items}
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
    calls = []  # (image, site, target(kernel-resolved), id)
    for name, path, base in IMAGES:
        d = open(path, 'rb').read()[0x200:]
        for site, t in bl_sites(d, base):
            v = r0_imm(md, d, base, site)
            if v is not None and v in ids:
                calls.append((name, site, veneer_target(d, base, t) if name == 'user' else t, v))
    # score targets: number of distinct NV ids passed
    by_t = collections.defaultdict(set)
    for _, _, t, v in calls:
        by_t[t].add(v)
    top = sorted(by_t.items(), key=lambda kv: -len(kv[1]))[:12]
    print('candidate NV access functions (target: distinct ids):')
    for t, s in top:
        print(f'  {t:#x}: {len(s)}')
    # Confirmed NV API in KERNEL 11.00 HK (nvitem.c / usernv.c), see docs/nv-map.md.
    # Allocators (threadx_mem.c, gki_mem.c, sdi_user_mem.c) also score high by chance and are excluded.
    nvfuncs = {0x81184010, 0x81184020, 0x80a2ef6e, 0x80a2f126, 0x80a2ef90, 0x80a2f016}
    # map callers to source files
    maps = {}
    for name, _, _ in IMAGES:
        try:
            m = json.load(open(f'{ROOT}/work/ghidra/{name}_modmap.json'))
            fs = sorted((int(f['a'], 16), f.get('src'), f.get('sub'), f['n']) for f in m['funcs'])
            maps[name] = ([x[0] for x in fs], fs)
        except FileNotFoundError:
            maps[name] = ([], [])
    use = collections.defaultdict(list)
    for name, site, t, v in calls:
        if t not in nvfuncs:
            continue
        addrs, fs = maps[name]
        k = bisect.bisect_right(addrs, site) - 1
        src = fs[k][1] if k >= 0 else None
        use[v].append(dict(img=name, site=hex(site), fn=hex(t), src=src))
    res = {}
    for iid, n, _ in items:
        u = use.get(iid, [])
        srcs = collections.Counter(x['src'] for x in u if x['src'])
        res[iid] = dict(size=n, n_refs=len(u), srcs=srcs.most_common(6),
                        imgs=sorted({x['img'] for x in u}))
    covered = sum(1 for r in res.values() if r['n_refs'])
    print(f'NV ids referenced from code: {covered}/{len(res)}')
    if out:
        json.dump(dict(nvfuncs=[hex(t) for t in nvfuncs], items=res), open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
