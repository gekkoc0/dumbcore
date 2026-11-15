#!/usr/bin/env python3
"""APN partition (apn.bin, 'BML APN Partition') parser.

Reader in USER: LoadNetworkAccountInfoFromOtaSection 0x88a1c9e2 -> ParseNetworkAccountInfo 0x88a1c63a
(mmiconn_manager_wintab.c). Layout, little-endian:

  0x00 char ver[16]   ('0' x 16)
  0x10 u32  size      (= file size - 0x14)
  0x14 'OTAC' u16 version(2) u16 count  u32 offset[count]   (offsets from 'OTAC')
  record (contiguous; parser checks off[i] + len == off[i+1]):
    +0x00 u16 ip_type          0 IPv4, 1 IPv6, 2 IPv4v6          -> link +0x174
    +0x02 u16 uiorder          list order (5 = default)          -> link +0x144
    +0x04 u16 mcc, +0x06 u16 mnc   kept only if they match the SIM (FUN_88555602)
    +0x08 u16 port             proxy port, 0 = none              -> link +0x08
    +0x0a u8  access_type      1 (0 only in the empty last record) -> link +0x00
    +0x0b u8  is_customed_detail -> link +0x133 = (v == 1); name printed by the link dump 0x882fb714
    +0x0c u8  auth_type        0 none, 1 PAP, 2 CHAP, 3 PAP/CHAP -> link +0x04
    +0x0d u8  account_type     0 internet, 1 mms, 5 ims, 6 ?, 8 xcap/ut (hos), 9 sos -> link +0x140
    +0x0e u8  mvno_type        0 none, 1 SPN, 2 GID, 3 PNN, 4 IMSI prefix, 5 IMSI range
    +0x0f u8  visible          0 = hidden in the settings list   -> link +0x178
    +0x10 u8  domestic_roaming? 1 only for MVNOs (iliad, Kena, PosteMobile, CoopVoce...) — unconfirmed
    +0x11 u8  roaming_ip_type  same codes as ip_type (correlates)
    +0x12 9 x {u16 len, data[len]} (NUL and padding inside len):
          name (UTF-16LE), gateway (proxy), dns1, dns2 (not copied), username, password, apn,
          homepage (MMSC for mms), mvno_value (matched according to mvno_type)
  converter OTA record -> link setting: USER 0x88a1d16e; link dump with field names: 0x882fb714.
  firmware clips the strings to CLIP chars.
"""
import struct, sys, collections

CLIP = [28, 80, 15, 15, 30, 30, 30, 40, 40]
STR = ['name', 'gateway', 'dns1', 'dns2', 'username', 'password', 'apn', 'homepage', 'mvno_value']
FLAGS = ['access_type', 'is_customed_detail', 'auth_type', 'account_type', 'mvno_type', 'visible', 'domestic_roaming', 'roaming_ip_type']


def parse(b):
    assert b[0x14:0x18] == b'OTAC', b[0x14:0x18]
    size, = struct.unpack_from('<I', b, 0x10)
    ver, n = struct.unpack_from('<HH', b, 0x18)
    base = 0x14
    offs = struct.unpack_from('<%dI' % n, b, 0x1c)
    recs = []
    for i, o in enumerate(offs):
        p = base + o
        ip_type, uiorder, mcc, mnc, port = struct.unpack_from('<5H', b, p)
        flags = list(b[p + 10:p + 18])
        q = p + 0x12
        strs = []
        for k in range(9):
            ln, = struct.unpack_from('<H', b, q)
            raw = b[q + 2:q + 2 + ln]
            if k == 0:
                v = raw.decode('utf-16le', 'replace').split('\0')[0]
            else:
                v = raw.split(b'\0')[0].decode('latin-1')
            strs.append(v)
            q += 2 + ln
        end = q
        nxt = base + offs[i + 1] if i + 1 < n else None
        recs.append({'i': i, 'off': p, 'len': end - p, 'gap': (nxt - end) if nxt else None,
                     'ip_type': ip_type, 'uiorder': uiorder, 'mcc': mcc, 'mnc': mnc, 'port': port,
                     **dict(zip(FLAGS, flags)), **dict(zip(STR, strs))})
    tail = len(b) - recs[-1]['off'] - recs[-1]['len'] if recs else None
    return {'size': size, 'ver': ver, 'n': n, 'recs': recs, 'tail': tail, 'hdr': b[:16]}


if __name__ == '__main__':
    import csv
    d = parse(open(sys.argv[1], 'rb').read())
    rs = d['recs']
    print('hdr', d['hdr'], 'size', d['size'], 'ver', d['ver'], 'records', d['n'], 'tail', d['tail'],
          'contiguous', all(r['gap'] in (0, None) for r in rs))
    if len(sys.argv) > 2:  # export CSV
        cols = ['i', 'mcc', 'mnc', 'uiorder', 'ip_type', 'port'] + FLAGS + STR
        with open(sys.argv[2], 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rs:
                w.writerow([r[c] for c in cols])
        print('csv ->', sys.argv[2])
    else:
        for k in ['ip_type', 'uiorder'] + FLAGS:
            print(f'{k:<17}', collections.Counter(r[k] for r in rs).most_common(8))
