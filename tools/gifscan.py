import sys, re, os
def gif_end(d, o):
    p = o + 13
    flags = d[o+10]
    if flags & 0x80: p += 3 * (2 << (flags & 7))
    frames = 0
    while p < len(d):
        b = d[p]
        if b == 0x3B: return p + 1, frames
        if b == 0x21:
            p += 2
            while d[p]: p += d[p] + 1
            p += 1
        elif b == 0x2C:
            frames += 1
            lf = d[p+9]; p += 10
            if lf & 0x80: p += 3 * (2 << (lf & 7))
            p += 1
            while d[p]: p += d[p] + 1
            p += 1
        else: return None, frames
    return None, frames
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
d = open(src, 'rb').read()
for m in re.finditer(b'GIF8[79]a', d):
    o = m.start(); e, n = gif_end(d, o)
    w, h = int.from_bytes(d[o+6:o+8], 'little'), int.from_bytes(d[o+8:o+10], 'little')
    print(f"0x{o:x} {w}x{h} frames={n} bytes={(e-o) if e else '?'}")
    if e: open(os.path.join(out, f"gif_{o:x}_{w}x{h}_{n}f.gif"), 'wb').write(d[o:e])
