#!/usr/bin/env python3
"""Put a TrueType font into mmi_res: rebuild the stock sfon fonts of the chosen scripts from a .ttf/.ttc.

    ttf2sfon.py <in mmi_res.bin> <out.bin> <font.ttf|font.ttc[:face]> [--scripts latn,cyrl] [--xheight N]

For every character of the stock font (same character set, same glyph numbers): if the TTF has it, its outline
replaces the stock one; otherwise the stock outline stays (re-encoded as a simple glyph so it no longer depends on
other glyphs). Outlines are scaled so the new font looks as big as the stock Latin font: the visible x-height
(stock 'x' height x strike size/128) is kept for every script, so Latin and Cyrillic end up the same size.
Advance widths are stored, as in the stock fonts, in 1/32 em (one byte).
Only TrueType outlines (glyf) are supported. Reads/writes local files only.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sres import Sres
from sfon import Sfon
from ttf import TTF
from sreswrite import SresWriter
import sfonwrite as W


def bbox_ymax(contours):
    ys = [p[1] for c in contours for p in c]
    return max(ys) if ys else 0


def convert(stock_bytes, ttf, target_xh=None):
    """-> (new sfon bytes, report dict, effective x-height used)"""
    F = Sfon(stock_bytes)
    st = F.strikes[0]
    hdr = st['hdr']
    size_byte, dflt = hdr[0], hdr[0x10]
    if target_xh is None:
        target_xh = bbox_ymax(F.outline(F.cmap[ord('x')])) * size_byte / 128 if ord('x') in F.cmap else None
    tx = bbox_ymax(ttf.outline(ttf.cmap[ord('x')]))
    # coordinate scale: ttf units -> stock units, compensating the strike size byte
    scale = (target_xh / (size_byte / 128)) / tx * (F.upem / ttf.upem) if target_xh and tx else F.upem / ttf.upem
    by_gid = {}
    for cp, g in sorted(F.cmap.items()):
        by_gid.setdefault(g, []).append(cp)
    glyphs, rep = {}, dict(replaced=0, kept=0, missing=[], composites_kept=0)
    replaced = {g for g, cps in by_gid.items() if any(c in ttf.cmap for c in cps)}

    def comps_closure(g, acc):
        r = F.glyph_record(g)
        if r and r['composite'] is not None:
            for c in r['composite']:
                if c['gid'] not in acc:
                    acc.add(c['gid'])
                    comps_closure(c['gid'], acc)
        return acc

    for g, cps in by_gid.items():
        cp = next((c for c in cps if c in ttf.cmap), None)
        if cp is not None:
            tg = ttf.cmap[cp]
            cont = [[(round(x * scale), round(y * scale), t) for x, y, t in c] for c in ttf.outline(tg)]
            adv = max(0, min(255, round(ttf.advance(tg) * scale * 32 / F.upem)))
            rep['replaced'] += 1
            glyphs[g] = W.encode_glyph(adv, dflt, contours=cont, flags=0x02 | (0x08 if adv != dflt else 0))
            continue
        rep['kept'] += 1
        rep['missing'].append(cps[0])
        deps = comps_closure(g, set())
        if deps and not deps & replaced:
            # stock composite whose parts all stay stock: copy it and its parts byte for byte
            glyphs[g] = F.glyph(g)
            for c in deps:
                glyphs.setdefault(c, F.glyph(c))
            rep['composites_kept'] += 1
        else:
            cont = [[(round(x), round(y), t) for x, y, t in c] for c in F.outline(g)]
            adv = F.glyph_record(g)['advance_raw']
            glyphs[g] = W.encode_glyph(adv, dflt, contours=cont, flags=0x02 | (0x08 if adv != dflt else 0))
    strike = W.build_strike(glyphs, size_byte, dflt, hdr[0x15], hdr[0x16], hdr[0x17], extra_hdr=hdr)
    cmap = W.build_cmap({cp: g for g, cps in by_gid.items() for cp in cps})
    out = W.build_sfon(F.script, F.upem, cmap, strike)
    return out, rep, target_xh


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    opts = dict(a[2:].split('=', 1) for a in argv[1:] if a.startswith('--') and '=' in a)
    src, dst, fontspec = args[0], args[1], args[2]
    path, _, face = fontspec.partition(':')
    ttf = TTF(open(path, 'rb').read(), int(face or 0))
    scripts = opts.get('scripts', 'latn,cyrl').split(',')
    s = Sres(src)
    w = SresWriter(src)
    fm = [m for m in s.modules if m['types'][4][1]][0]
    fonts = s.fonts(fm)
    target = float(opts['xheight']) if 'xheight' in opts else None
    if target is None:          # reference: the stock Latin font
        lat = next((f for f in fonts if f['script'] == 'latn'), None)
        if lat:
            L = Sfon(s.d[lat['off']:lat['off'] + lat['size']])
            target = bbox_ymax(L.outline(L.cmap[ord('x')])) * L.strikes[0]['hdr'][0] / 128
    print(f'{ttf.name}: upem {ttf.upem}; target visible x-height {target:.0f} units')
    for i, f in enumerate(fonts):
        if f['script'] not in scripts:
            continue
        new, rep, _ = convert(s.d[f['off']:f['off'] + f['size']], ttf, target)
        w.set_font(fm['index'], i, new)
        miss = ''.join(chr(c) for c in rep['missing'][:40])
        print(f"font {i} {f['script']}: {rep['replaced']} glyphs from TTF, {rep['kept']} stock kept "
              f"({miss}{'…' if len(rep['missing']) > 40 else ''}), of them {rep['composites_kept']} composites copied as is; "
              f"{f['size']} -> {len(new)} bytes")
    data = w.build()
    open(dst, 'wb').write(data)
    print(f'{dst}: {len(data)} bytes (original {len(s.d)})')


if __name__ == '__main__':
    main(sys.argv)
