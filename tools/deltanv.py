#!/usr/bin/env python3
"""Delta NV: patches applied on top of nvitem at boot.

Section (both the DeltaNV partition and the kernel-embedded operator blob), little-endian, unaligned:
  char name[20], u16 version, u32 size (whole section, header included)
  items until 0xffff or section end: {u16 nv_id, u16 offset, u16 len, data[len]}  -> nv[nv_id][offset:offset+len] = data
1) DeltaNV partition (`*_deltanv.bin`, 'BML delta NV Partition', loaded to RAM 0x80988800, max 128 KB;
   KERNEL nv_hwversion_adpter.c): sections 'hw_verNN', NN = board revision read from strap GPIOs (0x80a2e55e).
   NV_Force_Change 0x80a30ca2 applies the section if its version > the one stored in NV 0x16 byte 0x128.
   In every 3210 build both sections (hw_ver00 v0, hw_ver02 v1) are empty and NV_Force_Change has no caller.
   The partition is still read: Merge SIM/PLMN delta nv (0x80e7760c/0x80e776e6) looks the SIM up in it first
   ('delta nv bin', must start with a DeltaNvIndex section), then falls back to the kernel blob ('modem bin').
   WOTA writes its 'ims' file into this partition (0x889d5f26).
2) Kernel blob at 0x814fd768 (0x19000 bytes, signed with the kernel; KERNEL nvm_delta_nv.c):
   'DeltaNvIndex' section: entries of 16 bytes {u16 mnc (bit15 = 3-digit), u16 mcc, u32 -1, u32 off_S, u32 off_P}
   (offsets from blob start), then 331 operator pairs '<CC>_<Operator>_P' (patches NV 2162, IMS SIP/transport)
   and '_S' (patches NV 2160, IMS service/media), chosen by the SIM's MCC/MNC (0x80e77462);
   then 'hw_rfNNN' sections applied by RF chip id (NV_Force_Change_Ex 0x80a30e86, version in NV 0x16 byte 0x129).

    deltanv.py <deltanv.bin | EXEC_KERNEL_IMAGE.bin> [mcc]
"""
import struct, sys

KBLOB_SIZE = 0x19000  # 11.00 HK: 0x814fd768; other builds elsewhere -> located by find_blob()


def find_blob(k):
    """the 'DeltaNvIndex' section header (name padded with zeros to 20 bytes, sane size)."""
    p = -1
    while True:
        p = k.find(b'DeltaNvIndex\0', p + 1)
        if p < 0:
            return None
        size, = struct.unpack_from('<I', k, p + 22)
        if not any(k[p + 12:p + 20]) and 26 < size < KBLOB_SIZE:
            return p


def sections(b):
    p, out = 0, []
    while p + 26 <= len(b):
        name = b[p:p + 20].split(b'\0')[0]
        ver, = struct.unpack_from('<H', b, p + 20)
        size, = struct.unpack_from('<I', b, p + 22)
        if not name or size < 26:
            break
        items, q = [], p + 26
        while q + 2 <= min(p + size, len(b)):
            nid, = struct.unpack_from('<H', b, q)
            if nid == 0xffff or q + 6 > p + size:
                break
            off, ln = struct.unpack_from('<HH', b, q + 2)
            items.append({'nv': nid, 'off': off, 'len': ln, 'data': b[q + 6:q + 6 + ln]})
            q += 6 + ln
        out.append({'pos': p, 'name': name.decode('latin-1'), 'ver': ver, 'size': size, 'items': items})
        p += size
    return out, p


def index(b, sec):
    """DeltaNvIndex entries -> [(mcc, mnc_str, P_name, S_name)] (lookup 0x80e77462: flag==0 -> +0xc, else +8)"""
    by_pos = {s['pos']: s['name'] for s in sec}
    out = []
    for q in range(26, min(sec[0]['size'], len(b)) - 15, 16):
        mnc, mcc, _, os_, op = struct.unpack_from('<HHIII', b, q)
        m = '%03d' % (mnc & 0x7fff) if mnc & 0x8000 else '%02d' % mnc
        out.append((mcc, m, by_pos.get(op, hex(op)), by_pos.get(os_, hex(os_))))
    return out


if __name__ == '__main__':
    data = open(sys.argv[1], 'rb').read()
    if data[:6] == b'hw_ver':
        sec, end = sections(data)
        for s in sec:
            print(s['name'], 'ver', s['ver'], 'size', s['size'], 'items', len(s['items']))
        print('parsed', end, 'of', len(data), 'bytes; tail', data[end:].hex(' '))
    else:
        o, n = find_blob(data), KBLOB_SIZE
        blob = data[o:o + n]
        print(f'blob at file {o:#x} = {o - 0x200 + 0x80a06000:#x}')
        sec, end = sections(blob)
        idx = index(blob, sec)
        ops = [s for s in sec if s['name'].endswith(('_P', '_S'))]
        rf = [s for s in sec if s['name'].startswith('hw_rf')]
        print(f'sections {len(sec)}: index {len(idx)} entries, operator {len(ops)}, rf {[(s["name"], len(s["items"])) for s in rf]}; '
              f'used {end:#x} of {n:#x}, rest zero: {not any(blob[end:])}')
        nvs = {}
        for s in sec[1:]:
            for it in s['items']:
                nvs[it['nv']] = nvs.get(it['nv'], 0) + 1
        print('patched NV ids', nvs)
        want = int(sys.argv[2]) if len(sys.argv) > 2 else None
        for mcc, mnc, p, s in idx:
            if want is None or mcc == want:
                if want is not None or mcc in (1, 250):
                    print(f'  {mcc:03d}-{mnc:<3} {p:<24} {s}')
