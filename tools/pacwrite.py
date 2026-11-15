#!/usr/bin/env python3
"""Rebuild a Spreadtrum/Unisoc .pac (BP_R1.0.0) with some partition files replaced. Local files only.

    pacwrite.py <in.pac> <out.pac> [PARTITION_ID=file ...]      e.g. MMIRes=mmi_res_new.bin
    pacwrite.py <in.pac> --verify                                check the two checksums of a .pac

Layout (measured on all 8 firmware files, every one rebuilds byte for byte without changes):
  0x000 PAC_HEADER (0x84c bytes): version 'BP_R1.0.0' (UTF-16, 24 chars), +0x30 u32 total file size,
        +0x34 product (256 chars), +0x234 firmware name (256 chars), +0x434 u32 file count, +0x438 u32 offset of the
        file table (0x84c), mode / flash type / ... , +0x844 magic 0xFFFAFFFA,
        +0x848 u16 CRC1 = CRC-16/ARC of bytes [0, 0x848), +0x84a u16 CRC2 = CRC-16/ARC of bytes [0x84c, end).
  0x84c FILE_T x count, 0xa14 bytes each: u32 struct size, partition id / file name / version (UTF-16, 256 chars each),
        +0x604 u32 file size, flags, +0x610 u32 data offset in the .pac, ..., addresses.
  then the file data back to back in table order, no padding.
Signed images (FDL, BOOT, KERNEL, USER) must not be replaced: their DHTB signatures would fail (docs/secureboot.md).
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HDR, ENT = 0x84c, 0xa14
SIZE_AT, OFF_AT = 0x604, 0x610          # inside FILE_T (after the u32 struct size: raw[0] / raw[3])
SIGNED = {'FDL', 'FDL2', 'BOOT0', 'BOOT1', 'KernelImg', 'UserImg'}


def _crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        t.append(c)
    return t


_T = _crc_table()


def crc16_arc(data, c=0):
    t = _T
    for b in data:
        c = (c >> 8) ^ t[(c ^ b) & 0xff]
    return c


def wstr(b):
    return b.decode('utf-16le', 'replace').split('\x00', 1)[0]


def read(path):
    d = open(path, 'rb').read()
    count, start = struct.unpack_from('<II', d, 0x434)
    assert start == HDR, 'unexpected .pac header size'
    ents = []
    for i in range(count):
        e = d[start + ENT * i:start + ENT * (i + 1)]
        assert struct.unpack_from('<I', e, 0)[0] == ENT
        size, off = struct.unpack_from('<I', e, SIZE_AT)[0], struct.unpack_from('<I', e, OFF_AT)[0]
        ents.append(dict(id=wstr(e[4:516]), file=wstr(e[516:1028]), raw=bytearray(e), data=d[off:off + size] if size else b''))
    return d, ents


def build(d, ents):
    count = len(ents)
    out = bytearray(d[:HDR])
    pos = HDR + ENT * count
    table = bytearray()
    for e in ents:
        r = bytearray(e['raw'])
        struct.pack_into('<I', r, SIZE_AT, len(e['data']))
        struct.pack_into('<I', r, OFF_AT, pos if e['data'] else 0)
        table += r
        pos += len(e['data'])
    body = table + b''.join(e['data'] for e in ents)
    struct.pack_into('<I', out, 0x30, HDR + len(body))
    struct.pack_into('<I', out, 0x434, count)
    struct.pack_into('<H', out, 0x848, crc16_arc(out[:0x848]))
    struct.pack_into('<H', out, 0x84a, crc16_arc(body))
    return bytes(out + body)


def verify(d):
    c1, c2 = struct.unpack_from('<HH', d, 0x848)
    ok1 = crc16_arc(d[:0x848]) == c1
    ok2 = crc16_arc(d[HDR:]) == c2
    size_ok = struct.unpack_from('<I', d, 0x30)[0] == len(d)
    magic = struct.unpack_from('<I', d, 0x844)[0] == 0xFFFAFFFA
    return dict(crc1=ok1, crc2=ok2, size=size_ok, magic=magic)


def main(argv):
    src = argv[1]
    if len(argv) > 2 and argv[2] == '--verify':
        print(verify(open(src, 'rb').read()))
        return
    dst = argv[2]
    d, ents = read(src)
    for arg in argv[3:]:
        pid, path = arg.split('=', 1)
        e = next((x for x in ents if x['id'] == pid), None)
        if e is None:
            raise SystemExit(f'no partition {pid!r}; have: {", ".join(x["id"] for x in ents)}')
        if pid in SIGNED:
            raise SystemExit(f'{pid} is a signed image - replacing it would break secure boot; refused')
        new = open(path, 'rb').read()
        if pid == 'MMIRes' and new[:8] != b'sres0001':
            raise SystemExit('MMIRes must be an sres0001 file')
        print(f'{pid}: {len(e["data"])} -> {len(new)} bytes ({e["file"]})')
        e['data'] = new
    out = build(d, ents)
    open(dst, 'wb').write(out)
    print(f'{dst}: {len(out)} bytes, checks {verify(out)}', '| identical to input' if out == d else '')


if __name__ == '__main__':
    main(sys.argv)
