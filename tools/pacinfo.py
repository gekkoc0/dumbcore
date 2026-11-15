#!/usr/bin/env python3
"""Spreadtrum/Unisoc .pac (BP_R1.0.0) reader: list entries, optionally extract."""
import struct, sys, os

def wstr(b):
    return b.decode('utf-16le', 'replace').split('\x00', 1)[0]

def parse(path):
    f = open(path, 'rb')
    h = f.read(0x84c)
    ver = wstr(h[0:48])
    size, = struct.unpack_from('<I', h, 0x30)
    product = wstr(h[0x34:0x234])
    fwname = wstr(h[0x234:0x434])
    count, start = struct.unpack_from('<II', h, 0x434)
    f.seek(start)
    entries = []
    for i in range(count):
        ln, = struct.unpack('<I', f.read(4))
        body = f.read(ln - 4)
        pid = wstr(body[0:512])
        fname = wstr(body[512:1024])
        rest = body[1536:]
        u = struct.unpack_from('<%dI' % (len(rest) // 4), rest)
        entries.append(dict(id=pid, file=fname, raw=u))
    return dict(ver=ver, size=size, product=product, fw=fwname,
                count=count, start=start, entries=entries, fh=f)

if __name__ == '__main__':
    p = parse(sys.argv[1])
    print(f"{os.path.basename(sys.argv[1])}\n  ver={p['ver']} size={p['size']} product={p['product']} fw={p['fw']} n={p['count']}")
    for e in p['entries']:
        print(f"  {e['id']:<14} {e['file']:<60} {[hex(x) for x in e['raw'][:10]]}")

def extract(path, outdir):
    p = parse(path)
    os.makedirs(outdir, exist_ok=True)
    f = p['fh']
    for e in p['entries']:
        size, off = e['raw'][0], e['raw'][3]
        if e['file'] and size:
            f.seek(off)
            open(os.path.join(outdir, e['file']), 'wb').write(f.read(size))
    return p
