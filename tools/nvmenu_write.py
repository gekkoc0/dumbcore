#!/usr/bin/env python3
"""Записать главное меню (NV 680) в nvitem.bin — по JSON-плану из макета или кодами напрямую.

    nvmenu_write.py <nvitem.bin> <новый.nvitem.bin> <menu_edits.json>
    nvmenu_write.py <nvitem.bin> <новый.nvitem.bin> --grid 01,02,0c --list 01,02,0c

NV 680 (408 байт): u32 n_grid, u32 n_list, u32 grid[50], u32 list[50]  (коды, 0 = пусто).
JSON из макета (mockup → «⤓ Экспорт») содержит поля `grid` и `list` — массивы кодов нового порядка.
Дальше собрать .pac:  pacwrite.py <src.pac> <dst.pac> NV=<новый.nvitem.bin>
"""
import struct, sys, json, os
sys.path.insert(0, os.path.dirname(__file__))
from t117fw import nv_items

NV680 = 680
SZ = 408  # 4 + 4 + 50*4 + 50*4


def write_menu(nvpath, grid, lst):
    if len(grid) > 50 or len(lst) > 50:
        raise SystemExit(f'слишком много пунктов: сетка {len(grid)}, список {len(lst)} (макс 50)')
    b = bytearray(open(nvpath, 'rb').read())
    for iid, n, off in nv_items(nvpath)[1]:
        if iid == NV680:
            if n != SZ:
                raise SystemExit(f'NV 680 имеет размер {n}, ожидался {SZ}')
            g = list(grid) + [0] * (50 - len(grid))
            l = list(lst) + [0] * (50 - len(lst))
            data = struct.pack('<II', len(grid), len(lst)) + struct.pack('<50I', *g) + struct.pack('<50I', *l)
            b[off:off + n] = data
            return bytes(b)
    raise SystemExit('запись 680 не найдена в NV')


def main():
    a = sys.argv[1:]
    if '--grid' in a and '--list' in a:
        src, dst = a[0], a[1]
        gi, li = a.index('--grid'), a.index('--list')
        grid = [int(x, 16) for x in a[gi + 1].split(',') if x]
        lst = [int(x, 16) for x in a[li + 1].split(',') if x]
    else:
        src, dst, js = a[0], a[1], a[2]
        d = json.load(open(js))
        grid, lst = d['grid'], d['list']
    open(dst, 'wb').write(write_menu(src, grid, lst))
    print(f'{dst}: сетка {len(grid)} значков, список {len(lst)}')


if __name__ == '__main__':
    main()
