#!/usr/bin/env python3
"""Unisoc DHTB images: header + appended signature (secure boot), verified with pure Python.

Format (after verify_image() in fphelper_t117/fwcrypto.c, spreadtrum_flash, public domain):
  +0x000 'DHTB', u32 version=1, ..., +0x30 u32 payload_size; header is 0x200 bytes
  +0x200 payload
  then sign_head (0x60): +0x10 payload_size, +0x18 payload_offs(0x200), +0x20 sign_size, +0x28 sign_offs
  then sign_data:
     +0x000 u32 type (0 or 1)    +0x004 u32 key_bits    +0x008 e (4 bytes BE)   +0x00c n (key_bits/8, BE)
     +0x10c sha256(payload)      [type 1: +0x12c sha256(key_bits..n) — the key's own hash]
     +0x12c/+0x14c u32 extra_type=1, u32 version (anti-rollback?)
     +0x134/+0x154 RSA-PKCS#1 v1.5 signature over the 0x28/0x48 bytes starting at +0x10c

    dhtb.py <image.bin> [...]
"""
import hashlib, struct, sys


def parse(b):
    assert b[:4] == b'DHTB', 'no DHTB'
    ver, = struct.unpack_from('<I', b, 4)
    size, = struct.unpack_from('<I', b, 0x30)
    r = dict(version=ver, payload_size=size, tail=len(b) - 0x200 - size)
    if r['tail'] <= 0:
        r['signed'] = False
        return r
    sh = 0x200 + size
    sign_size, = struct.unpack_from('<I', b, sh + 0x20)
    sign_offs, = struct.unpack_from('<I', b, sh + 0x28)
    sd = b[sign_offs:sign_offs + sign_size]
    typ, bits = struct.unpack_from('<II', sd, 0)
    e = int.from_bytes(sd[8:12], 'big')
    n = int.from_bytes(sd[12:12 + bits // 8], 'big')
    key_blob = sd[4:4 + bits // 8 + 8]
    key_hash = hashlib.sha256(key_blob).hexdigest()
    payload_hash = hashlib.sha256(b[0x200:0x200 + size]).digest()
    p = typ * 0x20 + 0x12c
    extra_type, sver = struct.unpack_from('<Ii', sd, p)
    sig = int.from_bytes(sd[p + 8:p + 8 + bits // 8], 'big')
    dec = pow(sig, e, n).to_bytes(bits // 8, 'big')
    # PKCS#1 v1.5 type 1: 00 01 ff..ff 00 data
    ok_pad = dec[:2] == b'\x00\x01' and b'\x00' in dec[2:]
    data = dec[dec.index(b'\x00', 2) + 1:] if ok_pad else b''
    signed_len = typ * 0x20 + 0x28
    r.update(signed=True, sign_type=typ, key_bits=bits, e=e, key_hash=key_hash,
             key_hash_field=sd[0x12c:0x14c].hex() if typ == 1 else None,
             hash_ok=sd[0x10c:0x12c] == payload_hash,
             sig_ok=ok_pad and data == sd[0x10c:0x10c + signed_len],
             extra_type=extra_type, sign_version=sver,
             key_hash_self_ok=(sd[0x12c:0x14c].hex() == key_hash) if typ == 1 else None,
             modulus_head=hex(n)[:18])
    return r


if __name__ == '__main__':
    for path in sys.argv[1:]:
        r = parse(open(path, 'rb').read())
        print(path)
        for k, v in r.items():
            print(f'   {k:<16} {v}')
