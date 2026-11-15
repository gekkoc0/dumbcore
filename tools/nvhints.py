#!/usr/bin/env python3
"""For every NV id read/written from code, collect hints: log strings of the calling functions.

    nvhints.py <nvitem.bin> [out.json]
Uses tools/nvxref.py call-site detection and work/ghidra/<img>_funcs.jsonl (ExportFuncs.java).
API (KERNEL 11.00 HK): EFS_NvitemRead(id, len, buf) = 0x81184010; write = 0x81184020;
nvitem.c helpers 0x80a2ef6e / 0x80a2f126; user image reaches them through veneers.
"""
import json, os, re, sys, bisect, collections
sys.path.insert(0, os.path.dirname(__file__))
import capstone as cs
import nvxref
from t117fw import nv_items

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = {0x81184010: 'R', 0x81184020: 'W', 0x80a2ef6e: 'R', 0x80a2f126: 'R', 0x80a2ef90: 'R', 0x80a2f016: 'W'}
NOISE = re.compile(r'^[\W\d_]*$|^%|\.c$|^PNULL|^\s*$')


def load_funcs(name):
    fs = []
    for line in open(f'{ROOT}/work/ghidra/{name}_funcs.jsonl'):
        j = json.loads(line)
        fs.append((int(j['a'], 16), j))
    fs.sort(key=lambda x: x[0])
    srcmap = {}
    try:
        for f in json.load(open(f'{ROOT}/work/ghidra/{name}_modmap.json'))['funcs']:
            srcmap[f['a']] = f.get('src')
    except FileNotFoundError:
        pass
    return [a for a, _ in fs], [j for _, j in fs], srcmap


def main():
    nvpath = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    _, items, _, _ = nv_items(nvpath)
    sizes = {iid: n for iid, n, _ in items}
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
    hints = collections.defaultdict(lambda: dict(rw=set(), srcs=collections.Counter(), strs=collections.Counter(), sites=[]))
    for name, path, base in nvxref.IMAGES:
        d = open(path, 'rb').read()[0x200:]
        A, F, srcmap = load_funcs(name)
        for site, t in nvxref.bl_sites(d, base):
            rt = nvxref.veneer_target(d, base, t) if name == 'user' else t
            if rt not in API:
                continue
            v = nvxref.r0_imm(md, d, base, site)
            if v not in sizes:
                continue
            k = bisect.bisect_right(A, site) - 1
            f = F[k] if k >= 0 else None
            h = hints[v]
            h['rw'].add(API[rt])
            h['sites'].append(f'{name}:{site:#x}')
            if f:
                if srcmap.get(f['a']):
                    h['srcs'][srcmap[f['a']]] += 1
                for s in f['str']:
                    s = s.strip()
                    if len(s) >= 6 and not NOISE.search(s):
                        h['strs'][s[:100]] += 1
    res = {}
    for iid in sorted(sizes):
        h = hints.get(iid)
        if not h:
            continue
        res[iid] = dict(size=sizes[iid], rw=''.join(sorted(h['rw'])), sites=h['sites'][:6],
                        srcs=[s for s, _ in h['srcs'].most_common(3)],
                        hints=[s for s, _ in h['strs'].most_common(4)])
    for iid, r in res.items():
        print(f"{iid:5d} {r['size']:6d} {r['rw']:<2} {', '.join(r['srcs'])[:50]:<50} | {' | '.join(r['hints'])[:160]}")
    print(f'items with hints: {len(res)}/{len(sizes)}')
    if out:
        json.dump(res, open(out, 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
