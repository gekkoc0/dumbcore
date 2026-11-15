#!/usr/bin/env python3
"""SJPG (Unisoc 'small JPEG') -> standard JFIF.

SJPG = 'SJPG' + u16be height + u16be width + u16be a + u16be b + baseline JPEG entropy-coded data
(byte-stuffed, no markers, no tables). Decoder in KERNEL jpeg_hal.c / jpeg_interface.c (0x80b6d5dc, 0x810f4854).
Huffman tables are the standard ones (ITU-T T.81 Annex K); quant tables are the firmware's 5 levels
(LEVEL_LUMA/LEVEL_CHROMA, copied from the kernel and verified byte-for-byte), level = header field b.
Header field a = 3 for every stock image -> 4:2:2 (Y 2x1, Cb/Cr 1x1).

    sjpg.py <in.sjpg-blob> <out.jpg> [quality] [sampling 420|422|444]
"""
import struct, sys

# Annex K luminance / chrominance quantisation tables (zig-zag order applied below)
QL = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
      14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
      49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
QC = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99,
      47, 66, 99, 99, 99, 99, 99, 99] + [99] * 32
ZZ = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14,
      21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53,
      60, 61, 54, 47, 55, 62, 63]
# Annex K Huffman tables: (bits[16], values)
DC_L = ([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0], list(range(12)))
DC_C = ([0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0], list(range(12)))
AC_L = ([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d], bytes.fromhex(
    '01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a'
    '3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a929394'
    '95969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8'
    'e9eaf1f2f3f4f5f6f7f8f9fa'))
AC_C = ([0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77], bytes.fromhex(
    '000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728'
    '292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92'
    '939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7'
    'e8e9eaf2f3f4f5f6f7f8f9fa'))


# The firmware's own quant tables: KERNEL 11.00 HK @0x80a06000+0xb863a4 (luma) / +0xb864e4 (chroma),
# natural order, 5 levels = Annex K scaled to quality ~40/50/70/85/95. SJPG header field b = level.
# Right after them the kernel holds the Annex K Huffman tables used for every SJPG.
LEVEL_LUMA = [
    [20, 14, 13, 20, 30, 50, 64, 76, 15, 15, 18, 24, 33, 73, 75, 69, 18, 16, 20, 30, 50, 71, 86, 70, 18, 21, 28, 36, 64, 109, 100, 78, 23, 28, 46, 70, 85, 136, 129, 96, 30, 44, 69, 80, 101, 130, 141, 115, 61, 80, 98, 109, 129, 151, 150, 126, 90, 115, 119, 123, 140, 125, 129, 124],
    QL,
    [10, 7, 6, 10, 14, 24, 31, 37, 7, 7, 8, 11, 16, 35, 36, 33, 8, 8, 10, 14, 24, 34, 41, 34, 8, 10, 13, 17, 31, 52, 48, 37, 11, 13, 22, 34, 41, 65, 62, 46, 14, 21, 33, 38, 49, 62, 68, 55, 29, 38, 47, 52, 62, 73, 72, 61, 43, 55, 57, 59, 67, 60, 62, 59],
    [5, 3, 3, 5, 7, 12, 15, 18, 4, 4, 4, 6, 8, 17, 18, 17, 4, 4, 5, 7, 12, 17, 18, 17, 4, 5, 7, 9, 15, 26, 24, 19, 5, 7, 11, 17, 20, 33, 31, 23, 7, 11, 17, 19, 24, 31, 34, 28, 15, 19, 23, 26, 31, 36, 36, 30, 22, 28, 29, 29, 34, 30, 31, 30],
    [2, 1, 1, 2, 2, 4, 5, 6, 1, 1, 1, 2, 3, 6, 6, 6, 1, 1, 2, 2, 4, 6, 7, 6, 1, 2, 2, 3, 5, 9, 8, 6, 2, 2, 4, 6, 7, 11, 10, 8, 2, 4, 6, 6, 8, 10, 11, 9, 5, 6, 8, 9, 10, 12, 12, 10, 7, 9, 10, 10, 11, 10, 10, 10],
]
# chroma levels: only the top-left 4/4/3/2 coefficients of rows 0..3 differ from the capped tail value
LEVEL_CHROMA = []
for first, tail in (((21, 23, 30, 59, 23, 26, 33, 83, 30, 33, 70, 59, 83), 124), ((17, 18, 24, 47, 18, 21, 26, 66, 24, 26, 56, 47, 66), 99),
                    ((10, 11, 14, 28, 11, 13, 16, 40, 14, 16, 34, 28, 40), 59), ((5, 5, 7, 14, 5, 6, 8, 20, 7, 8, 17, 14, 20), 30),
                    ((2, 2, 2, 5, 2, 2, 3, 7, 2, 3, 6, 5, 7), 10)):
    t = [tail] * 64
    a = first
    t[0:4] = a[0:4]
    t[8:12] = a[4:8]
    t[16:19] = a[8:11]
    t[24:26] = a[11:13]
    LEVEL_CHROMA.append(t)
SAMPLING = {3: '422'}  # header field a; only 3 (=4:2:2) seen so far


def scale(q, quality):
    s = 5000 // quality if quality < 50 else 200 - 2 * quality
    return [min(255, max(1, (v * s + 50) // 100)) for v in q]


def seg(marker, body):
    return struct.pack('>BBH', 0xff, marker, len(body) + 2) + body


def to_jpeg(blob, quality=None, sampling=None, qtables=None):
    """quality=None/sampling=None -> take them from the SJPG header (firmware tables)."""
    assert blob[:4] == b'SJPG'
    h, w, a, b = struct.unpack('>4H', blob[4:12])
    data = blob[12:]
    if sampling is None:
        sampling = SAMPLING.get(a, '422')
    if qtables:
        ql, qc = qtables
    elif quality is None:
        lvl = min(b, 4)
        ql, qc = LEVEL_LUMA[lvl], LEVEL_CHROMA[lvl]
    else:
        ql, qc = scale(QL, quality), scale(QC, quality)
    dqt = bytes([0]) + bytes(ql[ZZ[i]] for i in range(64)) + bytes([1]) + bytes(qc[ZZ[i]] for i in range(64))
    hv = {'420': 0x22, '422': 0x21, '444': 0x11}[sampling]
    sof = struct.pack('>BHHB', 8, h, w, 3) + bytes([1, hv, 0, 2, 0x11, 1, 3, 0x11, 1])
    dht = b''
    for cls_id, (bits, vals) in ((0x00, DC_L), (0x10, AC_L), (0x01, DC_C), (0x11, AC_C)):
        dht += bytes([cls_id]) + bytes(bits) + bytes(vals)
    sos = bytes([3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0])
    return (b'\xff\xd8' + seg(0xdb, dqt) + seg(0xc0, sof) + seg(0xc4, dht) + seg(0xda, sos) + data
            + (b'' if data.endswith(b'\xff\xd9') else b'\xff\xd9')), (h, w, a, b)


if __name__ == '__main__':
    blob = open(sys.argv[1], 'rb').read()
    q = int(sys.argv[3]) if len(sys.argv) > 3 else None
    smp = sys.argv[4] if len(sys.argv) > 4 else None
    jpg, hdr = to_jpeg(blob, q, smp)
    open(sys.argv[2], 'wb').write(jpg)
    print('header h,w,a,b =', hdr)
