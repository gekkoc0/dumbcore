#!/usr/bin/env python3
"""Show the main menu stored in NV item 680 (read-only).

    nvmenu.py <nvitem.bin>

Item 680 (408 bytes): u32 n_grid, u32 n_list, u32 grid[50], u32 list[50]  (codes, 0 = empty).
The menu module (USER mmi_mainmenu_*.c, init 0x8833d66a in 11.00 HK) checks the length (0x198) and keeps only
codes present in its item table s_mainmenu_item_data. Names below come from that table + text resources.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from t117fw import nv_items

MENU = {
    0x01: ('Call logs', 'Журнал вызовов'), 0x02: ('Contacts', 'Контакты'), 0x03: ('Gallery', 'Галерея'),
    0x04: ('Internet', 'Интернет'), 0x05: ('Messages', 'Сообщения'), 0x06: ('Camera', 'Камера'),
    0x07: ('Facebook', 'Facebook'), 0x08: ('Radio', 'Радио'), 0x09: ('Alarm', 'Будильник'),
    0x0a: ('Music', 'Музыка'), 0x0b: ('Football cup', 'Football cup'), 0x0c: ('Settings', 'Параметры'),
    0x0d: ('Files', 'Файлы'), 0x0e: ('Extras', 'Дополнительно'), 0x0f: ('Himalaya', 'Himalaya'),
    0x11: ('Alipay', 'Alipay'), 0x12: ('Videos', 'Видео'), 0x14: ('Cloud', 'Cloud'),
    0x16: ('SIM ATK1', 'SIM-меню 1'), 0x17: ('SIM ATK2', 'SIM-меню 2'), 0x18: ('Racing Attack', 'Racing Attack'),
    0x19: ('Doodle Jump', 'Doodle Jump'), 0x1a: ('Crossy Road', 'Crossy Road'), 0x1b: ('Ninja Up', 'Ninja Up'),
    0x1c: ('Air Strike', 'Air Strike'), 0x1d: ('Snake', 'Змея'), 0x1e: ('Arrow Master', 'Arrow Master'),
    0x1f: ('Blackjack', 'Блэкджек'), 0x20: ('Calendar', 'Календарь'), 0x21: ('Calculator', 'Калькулятор'),
    0x22: ('Recorder', 'Диктофон'), 0x23: ('Torch', 'Фонарик'), 0x24: ('Counters', 'Счётчики'),
}


def read_menu(nvpath):
    b = open(nvpath, 'rb').read()
    for iid, n, off in nv_items(nvpath)[1]:
        if iid == 680:
            item = b[off:off + n]
            ng, nl = struct.unpack_from('<II', item, 0)
            grid = struct.unpack_from('<50I', item, 8)
            lst = struct.unpack_from('<50I', item, 208)
            return ng, nl, grid, lst
    raise SystemExit('item 680 not found')


def main():
    ng, nl, grid, lst = read_menu(sys.argv[1])
    for title, n, codes in (('сетка 3×3', ng, grid), ('список 1×1', nl, lst)):
        shown = [c for c in codes[:n] if c]
        print(f'{title}: {len(shown)} значков (счётчик в NV = {n})')
        for i, c in enumerate(shown):
            en, ru = MENU.get(c, ('?', '?'))
            print(f'  {i + 1:2d}. {c:#04x}  {ru} ({en})')
    used = set(grid[:ng]) | set(lst[:nl])
    hidden = [c for c in MENU if c not in used]
    print('есть в прошивке, но не в меню:', ', '.join(f'{c:#04x} {MENU[c][1]}' for c in hidden))


if __name__ == '__main__':
    main()
