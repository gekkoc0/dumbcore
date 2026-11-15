#!/usr/bin/env python3
"""List (and optionally extract) a FAT12/16 disk image from the phone backup (hidden disk C:, phone memory D:).
Read-only on the image.

    python3 -I tools/fat12ls.py backup/.../filesystem.bin            # tree with sizes
    python3 -I tools/fat12ls.py backup/.../filesystem.bin out_dir    # also extract files
"""
import os, struct, sys


class Fat:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        d = self.d
        self.bps, self.spc, self.res, self.nfat, self.nroot, ts16, _, self.spf = struct.unpack_from('<HBHBHHBH', d, 11)
        self.total = ts16 or struct.unpack_from('<I', d, 32)[0]
        self.fat_off = self.res * self.bps
        self.root_off = self.fat_off + self.nfat * self.spf * self.bps
        self.data_off = self.root_off + ((self.nroot * 32 + self.bps - 1) // self.bps) * self.bps
        self.csize = self.spc * self.bps
        clusters = (self.total * self.bps - self.data_off) // self.csize
        self.fat16 = clusters >= 4085

    def next(self, c):
        if self.fat16:
            return struct.unpack_from('<H', self.d, self.fat_off + 2 * c)[0]
        v = struct.unpack_from('<H', self.d, self.fat_off + c * 3 // 2)[0]
        return v >> 4 if c & 1 else v & 0xfff

    def chain(self, c):
        end = 0xfff8 if self.fat16 else 0xff8
        seen = set()
        while 2 <= c < end and c not in seen:
            seen.add(c)
            yield c
            c = self.next(c)

    def read(self, c, size=None):
        out = b''.join(self.d[self.data_off + (x - 2) * self.csize:self.data_off + (x - 1) * self.csize] for x in self.chain(c))
        return out if size is None else out[:size]

    def entries(self, raw):
        lfn = []
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xe5:
                lfn = []
                continue
            if e[11] == 0x0f:                            # long file name piece (UTF-16)
                lfn.insert(0, (e[1:11] + e[14:26] + e[28:32]).decode('utf-16le', 'replace').split('\x00')[0].rstrip('￿'))
                continue
            short = e[:8].decode('latin-1').rstrip() + ('.' + e[8:11].decode('latin-1').rstrip() if e[8:11].strip() else '')
            name = ''.join(lfn) or short
            lfn = []
            if e[11] & 8 or name in ('.', '..'):
                continue
            hi = struct.unpack_from('<H', e, 20)[0] if self.fat16 else 0
            yield name, e[11], (hi << 16) | struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]

    def walk(self, raw=None, path=''):
        if raw is None:
            raw = self.d[self.root_off:self.data_off]
        for name, attr, c, size in self.entries(raw):
            p = path + '/' + name
            if attr & 0x10:
                yield p, None, c
                yield from self.walk(self.read(c), p)
            else:
                yield p, size, c


def main(argv):
    f = Fat(argv[1])
    out = argv[2] if len(argv) > 2 else None
    files = dirs = total = 0
    for p, size, c in f.walk():
        if size is None:
            dirs += 1
            print(f'{"<dir>":>10}  {p}/')
            continue
        files += 1
        total += size
        print(f'{size:>10}  {p}')
        if out:
            dst = os.path.join(out, p.lstrip('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(f.read(c, size))
    print(f'-- {"FAT16" if f.fat16 else "FAT12"}, {f.total * f.bps} bytes, {dirs} dirs, {files} files, {total} bytes in files')


if __name__ == '__main__':
    main(sys.argv)
