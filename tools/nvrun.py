#!/usr/bin/env python3
"""Running NV (the phone's working NV store, partition 0x90000003, format VNTS) - read and patch items in place.

Format (fphelper_t117 scan_nv + checked on a real phone dump): header block "VNTS" (+4 NV id = first word of the fixed NV,
+8/+10 first/last item id, +14 block size, +16 directory count), header duplicated in the next block; directory of
{u16 link checksum over the next 14 bytes, u16 size, u32 offset} per id, also duplicated; each item at its offset:
{u16 header checksum over +4..+12, u16 data checksum, u16 id, u16 size, 4 bytes, data}. Checksum = one's complement
16-bit sum (nv_checksum). Only same-size rewrites are supported: the directory does not change, only the data and its
data checksum.

    nvrun.py <nv_running.bin> --get 680                        # show an item (checksums verified)
    nvrun.py <nv_running.bin> --menu                           # main menu (NV 680) with item names
    nvrun.py <nv_running.bin> <out.bin> --menu-add 20,21,23    # append menu codes (grid and list) after the last item
    nvrun.py <nv_running.bin> <out.bin> --menu-set 01,02,...   # set grid and list to exactly these codes (hex)
"""
import os, struct, sys

NV_MENU = 680
MENU_NAMES = {0x01: 'Журнал вызовов', 0x02: 'Контакты', 0x03: 'Галерея', 0x04: 'Интернет', 0x05: 'Сообщения',
              0x06: 'Камера', 0x07: 'Facebook', 0x08: 'Радио', 0x09: 'Будильник', 0x0a: 'Музыка', 0x0b: 'Football cup',
              0x0c: 'Параметры', 0x0d: 'Файлы', 0x0e: 'Дополнительно', 0x0f: 'Himalaya', 0x11: 'Alipay', 0x12: 'Видео',
              0x14: 'Cloud', 0x16: 'SIM-меню 1', 0x17: 'SIM-меню 2', 0x18: 'Racing Attack', 0x19: 'Doodle Jump',
              0x1a: 'Crossy Road', 0x1b: 'Ninja Up', 0x1c: 'Air Strike', 0x1d: 'Змея', 0x1e: 'Arrow Master',
              0x1f: 'Блэкджек', 0x20: 'Календарь', 0x21: 'Калькулятор', 0x22: 'Диктофон', 0x23: 'Фонарик',
              0x24: 'Счётчики'}


def checksum(b):
    c = 0
    for i in range(0, len(b) - 1, 2):
        c += b[i] | b[i + 1] << 8
    if len(b) & 1:
        c += b[-1]
    c = (c >> 16) + (c & 0xffff)
    c += c >> 16
    return ~c & 0xffff


def locate(d, item_id):
    """Return (directory entry offset, item offset, data size) after verifying all three checksums."""
    if d[:4] != b'VNTS':
        sys.exit('not a running NV image (no VNTS magic)')
    first, last = struct.unpack_from('<HH', d, 8)
    blk, dirc = struct.unpack_from('<HH', d, 14)
    if d[:blk] != d[blk:2 * blk]:
        sys.exit('VNTS header copies differ - image damaged, not touching it')
    if not first <= item_id <= last:
        sys.exit(f'id {item_id} outside {first}..{last}')
    p = 2 * blk + (item_id - first) * 16
    lchk, size, off = struct.unpack_from('<HHI', d, p)
    if checksum(d[p + 2:p + 16]) != lchk:
        sys.exit(f'directory checksum mismatch for id {item_id}')
    hchk, dchk, iid, isz = struct.unpack_from('<HHHH', d, off)
    if iid != item_id or isz != size or checksum(d[off + 4:off + 12]) != hchk:
        sys.exit(f'item header mismatch for id {item_id}')
    if checksum(d[off + 12:off + 12 + isz]) != dchk:
        sys.exit(f'data checksum mismatch for id {item_id}')
    return p, off, isz


def get_item(d, item_id):
    _, off, n = locate(d, item_id)
    return d[off + 12:off + 12 + n]


def set_item(d, item_id, data):
    """Rewrite an item's data (same size) and its data checksum; returns a new image."""
    _, off, n = locate(d, item_id)
    if len(data) != n:
        sys.exit(f'id {item_id}: new data is {len(data)} bytes, item is {n}')
    b = bytearray(d)
    b[off + 12:off + 12 + n] = data
    struct.pack_into('<H', b, off + 2, checksum(data))
    out = bytes(b)
    locate(out, item_id)                       # re-verify
    return out


def menu_codes(data):
    ng, nl = struct.unpack_from('<II', data, 0)
    grid = struct.unpack_from('<50I', data, 8)[:ng]
    lst = struct.unpack_from('<50I', data, 8 + 200)[:nl]
    return list(grid), list(lst)


def menu_data(grid, lst):
    if len(grid) > 50 or len(lst) > 50:
        sys.exit('at most 50 menu items')
    return (struct.pack('<II', len(grid), len(lst)) + struct.pack('<50I', *(list(grid) + [0] * (50 - len(grid))))
            + struct.pack('<50I', *(list(lst) + [0] * (50 - len(lst)))))


def show_menu(data):
    grid, lst = menu_codes(data)
    for title, codes in (('сетка', grid), ('список', lst)):
        print(f'{title}: {len(codes)} пунктов')
        print('   ' + ', '.join(f'{c:02x} {MENU_NAMES.get(c, "?")}' for c in codes))


def main(a):
    if len(a) < 2:
        sys.exit(__doc__)
    d = open(a[0], 'rb').read()
    if a[1] == '--get':
        data = get_item(d, int(a[2], 0))
        print(f'id {a[2]}: {len(data)} bytes, checksums OK\n{data.hex()}')
    elif a[1] == '--menu':
        show_menu(get_item(d, NV_MENU))
    elif len(a) >= 4 and a[2] in ('--menu-add', '--menu-set'):
        grid, lst = menu_codes(get_item(d, NV_MENU))
        codes = [int(x, 16) for x in a[3].split(',') if x]
        unknown = [c for c in codes if c not in MENU_NAMES]
        if unknown:
            sys.exit(f'unknown menu codes: {unknown}')
        if a[2] == '--menu-add':
            grid += [c for c in codes if c not in grid]
            lst += [c for c in codes if c not in lst]
        else:
            grid, lst = codes, list(codes)
        out = set_item(d, NV_MENU, menu_data(grid, lst))
        changed = [i for i in range(len(d)) if d[i] != out[i]]
        open(a[1], 'wb').write(out)
        print(f'{a[1]}: {len(changed)} bytes changed at {hex(changed[0])}..{hex(changed[-1])}' if changed else 'no change')
        show_menu(get_item(out, NV_MENU))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
