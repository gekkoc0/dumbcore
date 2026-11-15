#!/usr/bin/env python3
"""Replace images in mmi_res from PNG files and write a new mmi_res. Reads/writes local files only.

    sresedit.py <in mmi_res.bin> <out.bin> EDIT [EDIT ...]
      EDIT:  IMAGE_NAME_OR_ID=file.png         replace an image (ABMP/ABMR)
             COLOR_RES_NAME=#RRGGBB             replace a colour (stored as RGB565)
             text:MODULE:INDEX[@Language]=text  replace a string (all languages if @Language is omitted)
             ring:MODULE:INDEX=file             replace a sound (MIDI / WAV / MP3 / AMR; format code set automatically)
             anim:MODULE:INDEX=file.gif         replace an SMOV animation (frames of the GIF, same size)
      images may be ABMP/ABMR/sabm/BMP (from PNG), SGIF (from .gif) or SJPG wallpapers (from any picture, same size)
    sresedit.py <in mmi_res.bin> --names [filter]      # official resource names (cscs section)
    sresedit.py <in mmi_res.bin> --find TEXT [Language] # strings containing TEXT -> text:MODULE:INDEX
    sresedit.py <in mmi_res.bin> --colors               # colours with names and values
    sresedit.py <in mmi_res.bin> --langs                # languages of the build
    sresedit.py <in mmi_res.bin> --rings [export_dir]   # sounds; with a folder: export them as files

NAME_OR_ID: an official name from the cscs section (e.g. IMAGE_MAINMENU_ICON_CALCULATOR), or MODULE:INDEX
(e.g. 0:195), or a resource id 0x40MMIIII. The PNG must have the same width/height as the original.
The image is encoded in the same kind as the original (ABMP or ABMR, sabm wrapper kept) with the stock encoder
rules (tools/imgenc.py). Needs Pillow (work/.venv/bin/python).
"""
import sys, os, struct, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sres import Sres
from sreswrite import SresWriter
from imgcodec import unwrap, parse_abm
from imgenc import encode_rgba
import resenc, smov


def cscs_names(s):
    """official names: {name: (type, module, index)} from the cscs section."""
    sec = [x for x in s.sections if x[0] == 'cscs']
    if not sec:
        return {}
    _, off, size = sec[0]
    c = s.d[off:off + size]
    out, p = {}, 4
    while p + 13 <= len(c):
        typ, mod, _, idx, _ = struct.unpack_from('<BBHII', c, p)
        end = c.index(b'\0', p + 12)
        name = c[p + 12:end].decode('latin-1')
        out[name] = (typ, mod, idx)
        p = (end + 1 + 3) & ~3
    return out


def resolve(s, names, key):
    if key in names:
        typ, mod, idx = names[key]
        if typ != 0:
            raise SystemExit(f'{key}: not an image (type {typ})')
        return mod, idx
    m = re.fullmatch(r'(\d+):(\d+)', key)
    if m:
        return int(m[1]), int(m[2])
    if key.lower().startswith('0x'):
        v = int(key, 16)
        return (v >> 16) & 0xff, (v & 0xffff) - 1
    raise SystemExit(f'unknown resource {key!r}; use --names to list official names')


def languages(s):
    """language names in text-table order, from the 'lang' section: u32 0, then {u32 index, char name[20]}."""
    sec = [x for x in s.sections if x[0] == 'lang']
    if not sec:
        return []
    _, off, size = sec[0]
    d = s.d[off:off + size]
    out = {}
    for i in range((size - 4) // 24):
        idx, = struct.unpack_from('<I', d, 4 + 24 * i)
        out[idx] = d[8 + 24 * i:28 + 24 * i].split(b'\0')[0].decode('latin-1')
    return [out[i] for i in sorted(out)]


def parse_color(v):
    v = v.lstrip('#')
    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    return (r >> 3) << 11 | (g >> 2) << 5 | b >> 3


def rgb_hex(v):
    return '#%02x%02x%02x' % ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)


def main(argv):
    src = argv[1]
    s = Sres(src)
    names = cscs_names(s)
    if len(argv) > 2 and argv[2] == '--names':
        flt = argv[3].upper() if len(argv) > 3 else ''
        for n, (t, m, i) in sorted(names.items(), key=lambda x: x[1]):
            if flt in n:
                print(f'{n:<48} type {t} module {m} index {i}')
        return
    langs = languages(s)
    if len(argv) > 2 and argv[2] == '--langs':
        for i, n in enumerate(langs):
            print(i, n)
        return
    if len(argv) > 2 and argv[2] == '--rings':
        ext = {0: 'mid', 5: 'wav', 6: 'mp3', 8: 'amr'}
        out_dir = argv[3] if len(argv) > 3 else None
        for m in s.modules:
            for i, b in enumerate(s.blobs(m, 2)):
                e = ext.get(b['fmt'], 'bin')
                print(f"ring:{m['index']}:{i}  {e:<4} {b['size']:>8} bytes")
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    open(os.path.join(out_dir, f"ring_{m['index']}_{i}.{e}"), 'wb').write(s.d[b['off']:b['off'] + b['size']])
        return
    if len(argv) > 2 and argv[2] == '--colors':
        for m in s.modules:
            cname = {i: n for n, (t, mm, i) in names.items() if t == 6 and mm == m['index']}
            for i, (v, f) in enumerate(s.colors(m)):
                print(f"{cname.get(i, 'color:%d:%d' % (m['index'], i)):<40} {rgb_hex(v)}  (RGB565 {v:#06x})")
        return
    if len(argv) > 3 and argv[2] == '--find':
        needle = argv[3].lower()
        only = langs.index(argv[4]) if len(argv) > 4 else None
        for m in s.modules:
            tl = s.texts(m)
            for i in range(len(tl[0]) if tl else 0):
                vals = [s.string_at(tl[L][i]) for L in range(len(tl))]
                hit = [L for L, v in enumerate(vals) if needle in v.lower() and (only is None or L == only)]
                if hit:
                    show = ' | '.join(f'{langs[L] if L < len(langs) else L}: {vals[L]!r}' for L in sorted(set(hit + [0])))
                    print(f"text:{m['index']}:{i}  {show[:200]}")
        return
    dst = argv[2]
    w = SresWriter(src)
    for arg in argv[3:]:
        key, val = arg.split('=', 1)
        if key.startswith('text:'):
            parts = key.split(':')
            mod, rest = int(parts[1]), parts[2]
            idx, _, lang = rest.partition('@')
            idx = int(idx)
            mobj = w._mod(mod)
            nl = len(s.texts(mobj))
            targets = range(nl) if not lang else [langs.index(lang)]
            for L in targets:
                w.set_text(mod, idx, L, val)
            print(f"{key}: {len(list(targets))} language(s) -> {val!r}")
            continue
        if key.startswith('ring:'):
            _, mod, idx = key.split(':'); mod, idx = int(mod), int(idx)
            data = open(val, 'rb').read()
            fmt = resenc.ring_fmt(data)
            old = s.blobs(w._mod(mod), 2)[idx]
            w.set_blob(mod, 2, idx, data, fmt=fmt)
            print(f'{key}: format {old["fmt"]:#x} -> {fmt:#x}, {old["size"]} -> {len(data)} bytes')
            continue
        if key.startswith('anim:'):
            from PIL import Image, ImageSequence
            _, mod, idx = key.split(':'); mod, idx = int(mod), int(idx)
            b = s.blobs(w._mod(mod), 1)[idx]
            raw = s.d[b['off']:b['off'] + b['size']]
            if raw[:4] != b'SMOV':
                raise SystemExit(f'{key}: only SMOV animations can be replaced')
            info = smov.parse(raw)
            kind = chr(raw[info['offsets'][0] + 3])
            frames = []
            for fr in ImageSequence.Iterator(Image.open(val)):
                fr = fr.convert('RGBA')
                if fr.size != (b['w'], b['h']):
                    raise SystemExit(f'{key}: GIF is {fr.size}, animation is {b["w"]}x{b["h"]}')
                frames.append((fr.size[0], fr.size[1], fr.tobytes()))
            enc = resenc.smov_encode(frames, info['x'], kind)
            w.set_blob(mod, 1, idx, enc, fmt=(len(frames) << 16) | (b['fmt'] & 0xffff))
            print(f'{key}: {info["n"]} -> {len(frames)} frames, {len(raw)} -> {len(enc)} bytes')
            continue
        if key.startswith('COLOR_') or key.startswith('color:'):
            if key in names:
                typ, mod, idx = names[key]
            else:
                _, mod, idx = key.split(':'); mod, idx = int(mod), int(idx)
            old = s.colors(w._mod(mod))[idx][0]
            w.set_color(mod, idx, parse_color(val))
            print(f'{key}: {rgb_hex(old)} -> {rgb_hex(parse_color(val))}')
            continue
        from PIL import Image
        png = val
        mod, idx = resolve(s, names, key)
        mobj = w._mod(mod)
        b = s.blobs(mobj, 0)[idx]
        raw = s.d[b['off']:b['off'] + b['size']]
        if raw[:4] == b'SGIF':
            enc = resenc.sgif_wrap(open(png, 'rb').read(), b['w'], b['h'])
            kind = 'SGIF'
        elif raw[:4] == b'SJPG':
            im = Image.open(png).convert('RGB')
            if im.size != (b['w'], b['h']):
                raise SystemExit(f'{key}: picture is {im.size[0]}x{im.size[1]}, wallpaper is {b["w"]}x{b["h"]}')
            enc = resenc.sjpg_encode(im, level=struct.unpack('>H', raw[10:12])[0], a=struct.unpack('>H', raw[8:10])[0])
            kind = 'SJPG'
        else:
            im = Image.open(png).convert('RGBA')
            if im.size != (b['w'], b['h']):
                raise SystemExit(f'{key}: PNG is {im.size[0]}x{im.size[1]}, original is {b["w"]}x{b["h"]}')
            inner = unwrap(raw)
            if raw[:2] == b'BM':
                enc = resenc.bmp_encode(raw, b['w'], b['h'], resenc.rgba_rows565(b['w'], b['h'], im.tobytes()))
                kind = 'BMP'
            elif raw[:4] == b'sabm' and inner[:3] != b'ABM':
                enc = resenc.sabm_raw_encode(raw, b['w'], b['h'], im.tobytes())
                kind = 'sabm raw'
            elif inner[:3] == b'ABM' and chr(inner[3]) in 'PR':
                k_ = parse_abm(inner)['kind']
                enc = encode_rgba(b['w'], b['h'], im.tobytes(), kind=k_)
                if raw[:4] == b'sabm':
                    enc = raw[:12] + enc
                kind = 'ABM' + k_
            else:
                raise SystemExit(f'{key}: format {raw[:4]!r} cannot be replaced')
        w.set_blob(mod, 0, idx, enc)
        print(f'{key}: module {mod} index {idx}, {kind}, {len(raw)} -> {len(enc)} bytes')
    data = w.build()
    open(dst, 'wb').write(data)
    print(f'{dst}: {len(data)} bytes (original {len(s.d)})')


if __name__ == '__main__':
    main(sys.argv)
