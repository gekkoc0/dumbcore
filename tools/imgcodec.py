"""Decoders for Unisoc MOCOR proprietary image formats: ABMP/ABMR (+S/T/Q/U variants), sabm wrapper.

Taken from the firmware's own decoder (kernel, alpha_res_decoder.c, 0x80ba4a40..0x80ba7500 in 3210 11.00 HK),
see docs/sres-format.md.

Header ('ABM' + kind), big-endian:
  +4 u16 w, +6 u16 h, +8 u16 a (index of first semi-transparent colour), +10 u16 b (number of them)
  +12 u8 top, +13 left, +14 bottom, +15 right  -> pixels exist only in x0..x1, y0..y1
  N = a + b; bits = ceil(log2 N) (min 1)
  P,R,S,T: palette (N-1) x u16 RGB565; Q,U: palette (N-1) x 3 bytes
  alpha:  P,R,Q,U: b bytes; S,T: b nibbles (high nibble first), mapped through NIBBLE_ALPHA
  data starts at the next even offset.
Pixel value v: 0 = transparent; 1..a-1 = palette[v-1] opaque; a..N-1 = palette[v-1] with alpha[v-a].
  P,S,Q: indices in big-endian 16-bit words taken LSB-first, row-major over the box, no row padding.
  R,T,U: u32le L; L bytes of row runs; then the packed index stream.
         index stream: little-endian 16-bit words, LSB-first.
         per row: pairs (n, f): n literal indices, then (if f) one index repeated f times; (0,0) ends the row.
"""
import struct, math, zlib

NIBBLE_ALPHA = [2, 4, 8, 16, 32, 48, 64, 80, 102, 124, 146, 168, 190, 212, 234, 254]


def rgb565(v):
    return ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31


class BitReader:
    """Stream of 16-bit words, bits taken LSB-first (firmware: value = (word >> bitpos) & mask).
    big_endian=True for ABMP-style (ldrh + rev16), False for ABMR-style row streams (plain ldrh).
    Past the end reads zeros (the encoder trims trailing zero bytes)."""
    def __init__(self, data, base, big_endian=True):
        self.d, self.base, self.pos, self.be = data, base, 0, big_endian

    def _word(self, i):
        o = self.base + 2 * i
        b0 = self.d[o] if o < len(self.d) else 0
        b1 = self.d[o + 1] if o + 1 < len(self.d) else 0
        return (b0 << 8) | b1 if self.be else (b1 << 8) | b0

    def read(self, bits):
        wi, sh = divmod(self.pos, 16)
        v = self._word(wi) >> sh
        if sh + bits > 16:
            v |= self._word(wi + 1) << (16 - sh)
        self.pos += bits
        return v & ((1 << bits) - 1)


def parse_abm(b):
    kind = chr(b[3])
    w, h, a, nb = struct.unpack('>HHHH', b[4:12])
    top, left, bottom, right = b[12:16]
    N = a + nb
    bits = 1
    while (2 << (bits - 1)) < N and bits < 16:
        bits += 1
    p = 16
    lut = [(0, 0, 0, 0)]
    if kind in 'QU':
        pal = [tuple(b[p + 3 * i:p + 3 * i + 3]) for i in range(N - 1)]
        p += 3 * (N - 1)
    else:
        pal = [rgb565(struct.unpack_from('>H', b, p + 2 * i)[0]) for i in range(N - 1)]
        p += 2 * (N - 1)
    if kind in 'ST':
        nib = [(b[p + (i >> 1)] >> (0 if i & 1 else 4)) & 15 for i in range(nb)]
        alpha = [NIBBLE_ALPHA[x] for x in nib]
        p += ((nb & 1) + (nb >> 1) + 1) & ~1
    else:
        alpha = list(b[p:p + nb])
        p += nb
        p += p & 1
    for v in range(1, N):
        lut.append(pal[v - 1] + ((alpha[v - a] if v >= a else 255),))
    return dict(kind=kind, w=w, h=h, a=a, b=nb, N=N, bits=bits,
                x0=left, y0=top, x1=w - 1 - right, y1=h - 1 - bottom, lut=lut, data=p)


def decode_abm(b):
    """-> (w, h, rgba bytearray). Raises on malformed input."""
    H = parse_abm(b)
    w, h, bits, lut = H['w'], H['h'], H['bits'], H['lut']
    x0, y0, x1, y1 = H['x0'], H['y0'], H['x1'], H['y1']
    out = bytearray(w * h * 4)

    def put(x, y, v):
        if v and 0 <= x < w and 0 <= y < h:
            o = (y * w + x) * 4
            out[o:o + 4] = bytes(lut[v] if v < len(lut) else (255, 0, 255, 255))

    if H['kind'] in 'PSQ':
        br = BitReader(b, H["data"])
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                put(x, y, br.read(bits))
    else:
        p = H['data']
        L, = struct.unpack_from('<I', b, p)
        runs = p + 4
        br = BitReader(b, p + 4 + L, big_endian=False)
        cw = x1 - x0 + 1
        for y in range(y0, y1 + 1):
            x = 0
            while True:
                n, f = b[runs], b[runs + 1]
                runs += 2
                if n == 0 and f == 0:
                    break
                for _ in range(n):
                    put(x0 + x, y, br.read(bits)); x += 1
                if f:
                    v = br.read(bits)
                    for _ in range(f):
                        put(x0 + x, y, v); x += 1
                if x > cw + 255:
                    raise ValueError('run overflow')
    return w, h, out


def unwrap(b):
    """strip 'sabm' wrapper (12 bytes) if present."""
    return b[12:] if b[:4] == b'sabm' else b


def decode_sabm_raw(b):
    """'sabm' whose payload is not ABM: raw 32-bit pixels, w*h*4 bytes.
    Byte order assumed B,G,R,A (ARGB8888 little-endian, usual on ARM) — not yet confirmed from code."""
    w, h = struct.unpack('>HH', b[8:12])
    px = b[12:12 + w * h * 4]
    if len(px) != w * h * 4:
        return None
    out = bytearray(len(px))
    out[0::4], out[1::4], out[2::4], out[3::4] = px[2::4], px[1::4], px[0::4], px[3::4]
    return w, h, out


def decode_any(b):
    """BMP/GIF/JPEG are left to standard tools; this handles the proprietary ones."""
    if b[:4] == b'sabm' and b[12:15] != b'ABM':
        return decode_sabm_raw(b)
    b = unwrap(b)
    if b[:3] == b'ABM':
        return decode_abm(b)
    return None


def png_bytes(w, h, rgba):
    raw = b''.join(b'\0' + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(t, body):
        return struct.pack('>I', len(body)) + t + body + struct.pack('>I', zlib.crc32(t + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def contact_sheet(tiles, cell=64, per_row=16, bg=(90, 90, 110)):
    W = cell * per_row
    H = cell * max(1, math.ceil(len(tiles) / per_row))
    sheet = bytearray(bytes(bg + (255,)) * (W * H))
    for k, (w, h, px) in enumerate(tiles):
        ox, oy = (k % per_row) * cell + 2, (k // per_row) * cell + 2
        for y in range(min(h, cell - 2)):
            for x in range(min(w, cell - 2)):
                p = (y * w + x) * 4
                a = px[p + 3]
                if a:
                    q = ((oy + y) * W + ox + x) * 4
                    for c in range(3):
                        sheet[q + c] = (px[p + c] * a + sheet[q + c] * (255 - a)) // 255
    return W, H, sheet
