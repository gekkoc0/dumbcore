#!/usr/bin/env python3
"""Export every image/anim resource of an mmi_res file.

    python3 -I tools/export_images.py <mmi_res.bin> <out_dir>

Files: <out_dir>/m<module>_<type>_<index>_<w>x<h>.<ext>
  ABMP/ABMR/sabm -> .png (decoded), BMP -> .bmp, SGIF -> .gif, SJPG -> .jpg,
  SMOV/VM animations -> .gif, others -> .bin
Also writes <out_dir>/index.html with every image on one page.
"""
import os, sys, html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sres import Sres
from imgcodec import decode_any, png_bytes
from sjpg import to_jpeg
from smov import smov_frames
from vmbmp import rgba_frames as vm_frames
import io

TYPES = {0: 'img', 1: 'anim'}


def frames_gif(frames, ms=100):
    from PIL import Image
    ims = [Image.frombytes('RGBA', (w, h), bytes(px)) for w, h, px in frames]
    buf = io.BytesIO()
    ims[0].save(buf, 'GIF', save_all=True, append_images=ims[1:], duration=ms, loop=0, disposal=2)
    return buf.getvalue()


def main(src, out):
    s = Sres(src)
    d = s.d
    os.makedirs(out, exist_ok=True)
    rows, stats = [], {}
    for m in s.modules:
        for k, tname in TYPES.items():
            for i, bl in enumerate(s.blobs(m, k)):
                raw = d[bl['off']:bl['off'] + bl['size']]
                base = f"m{m['index']:02d}_{tname}_{i:04d}_{bl['w']}x{bl['h']}"
                ext, data = 'bin', raw
                try:
                    if raw[:3] == b'ABM' or raw[:4] == b'sabm':
                        r = decode_any(raw)
                        if r:
                            ext, data = 'png', png_bytes(*r)
                    elif raw[:2] == b'BM':
                        ext = 'bmp'
                    elif raw[:4] == b'SGIF':
                        ext, data = 'gif', raw[raw.index(b'GIF8'):]
                    elif raw[:4] == b'SJPG':
                        ext, data = 'jpg', to_jpeg(raw)[0]
                    elif raw[:4] == b'SMOV' or raw[:2] == b'VM':
                        fr = smov_frames(raw) if raw[:4] == b'SMOV' else vm_frames(raw)
                        ext, data = 'gif', frames_gif(fr)
                except Exception as e:  # keep going, keep the raw blob
                    ext, data = 'bin', raw
                    print('fail', base, e)
                name = f'{base}.{ext}'
                open(os.path.join(out, name), 'wb').write(data)
                stats[ext] = stats.get(ext, 0) + 1
                rows.append((m['index'], name, bl['w'], bl['h'], ext))
    with open(os.path.join(out, 'index.html'), 'w') as f:
        f.write('<!doctype html><meta charset="utf-8"><title>mmi_res images</title>'
                '<style>body{background:#5a5a6e;font:11px sans-serif;color:#eee}'
                'div{display:inline-block;margin:4px;text-align:center;vertical-align:top}'
                'img{image-rendering:pixelated;max-width:240px;display:block;margin:auto}</style>')
        cur = None
        for mod, name, w, h, ext in rows:
            if mod != cur:
                f.write(f'<h3>module {mod}</h3>')
                cur = mod
            tag = f'<img src="{html.escape(name)}">' if ext in ('png', 'bmp', 'gif', 'jpg') else '[raw]'
            f.write(f'<div>{tag}{html.escape(name)}</div>')
    print(stats, '->', out)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
