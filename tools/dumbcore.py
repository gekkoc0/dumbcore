#!/usr/bin/env python3
"""DumbCore — единая точка входа. Обёртка над скриптами tools/ с читаемыми подкомандами.

    python3 -I tools/dumbcore.py help
    python3 -I tools/dumbcore.py inspect mmi_res_240X320_QB.bin
    python3 -I tools/dumbcore.py edit mmi_res.bin new.bin IMAGE_MAINMENU_ICON_CALCULATOR=значок.png
    python3 -I tools/dumbcore.py font mmi_res.bin new.bin font.ttf
    python3 -I tools/dumbcore.py menu ums9117_*_nvitem_*.bin

Полный список подкоманд — `help`. Каждая команда — тонкая обёртка над соответствующим скриптом tools/.
"""
import sys, os, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))


def run(tool, *args):
    return subprocess.run([sys.executable, '-I', os.path.join(HERE, tool), *args])


def cmd_inspect(a):
    p = a.file
    if not os.path.exists(p):
        print('нет файла:', p); return 2
    head = open(p, 'rb').read(16)
    if head.startswith(b'sres0001'):
        print('→ ресурсы (sres.py)'); run('sres.py', p)
    elif head[:4] == b'DHTB':
        print('→ подписанный образ DHTB (dhtb.py)'); run('dhtb.py', p)
    elif head.startswith(b'BP_R') or p.lower().endswith('.pac'):
        print('→ контейнер .pac (pacinfo.py)'); run('pacinfo.py', p)
    elif head[:4] == b'OTAC':
        print('→ база APN (apn.py)'); run('apn.py', p)
    elif head[0] == 0xEB and head[2] in (0x90, 0x3C, 0x58):
        print('→ образ диска FAT (fat12ls.py)'); run('fat12ls.py', p)
    elif head[:4] == b'sfon':
        print('→ шрифт SPML (sfon.py)'); run('sfon.py', p)
    else:
        print('тип не определён по магии. Скорее всего это NV (nvmenu.py) — пробую:')
        run('nvmenu.py', p)
        print('Если не оно — список инструментов: tools/ и docs/')
    return 0


def main():
    ap = argparse.ArgumentParser(prog='dumbcore', description='DumbCore — инструменты для Nokia 3210 4G (UMS9117/Mocor/S30+)')
    s = ap.add_subparsers(dest='cmd', metavar='КОМАНДА')

    p = s.add_parser('help', help='показать справку по командам')
    p = s.add_parser('inspect', help='разобрать файл (тип по магии)'); p.add_argument('file')

    p = s.add_parser('edit', help='изменить ресурсы: иконки, тексты, цвета, звуки (sresedit.py)')
    p.add_argument('src'); p.add_argument('dst'); p.add_argument('edits', nargs='*',
        help='ИМЯ_КАРТИНКИ или М:Н=файл.png | text:М:Н@Russian=… | COLOR_RES_…=#RRGGBB | ring:М:Н=файл.mp3 | anim:М:Н=файл.gif')

    p = s.add_parser('font', help='поставить TrueType-шрифт (ttf2sfon.py)')
    p.add_argument('src'); p.add_argument('dst'); p.add_argument('ttf'); p.add_argument('--scripts', default='latn,cyrl')

    p = s.add_parser('menu', help='главное меню из NV 680 (nvmenu.py)'); p.add_argument('nvitem')

    p = s.add_parser('apn', help='база APN (apn.py)'); p.add_argument('apn'); p.add_argument('--csv', nargs='?')

    p = s.add_parser('pac', help='собрать .pac с заменёнными разделами (pacwrite.py)')
    p.add_argument('src'); p.add_argument('dst'); p.add_argument('replace', nargs='*', help='Раздел=файл')

    p = s.add_parser('mockup', help='макет телефона в браузере (mockup.py)')
    p.add_argument('mmi_res'); p.add_argument('nvitem'); p.add_argument('user', help='user.bin / EXEC_USER_IMAGE.bin той же сборки')
    p.add_argument('out', nargs='?')

    p = s.add_parser('images', help='выгрузить все картинки ресурсов (export_images.py)')
    p.add_argument('mmi_res'); p.add_argument('outdir')

    p = s.add_parser('dump', help='бэкап телефона, только чтение (dump_phone.sh)')
    p.add_argument('mode', nargs='?', default='test', choices=['test', 'full', 'extra', 'scan', 'hidden'])

    a = ap.parse_args()
    if not a.cmd or a.cmd == 'help':
        ap.print_help(); return 0
    if a.cmd == 'inspect': return cmd_inspect(a)
    if a.cmd == 'edit': return run('sresedit.py', a.src, a.dst, *a.edits).returncode
    if a.cmd == 'font': return run('ttf2sfon.py', a.src, a.dst, a.ttf, '--scripts=' + a.scripts).returncode
    if a.cmd == 'menu': return run('nvmenu.py', a.nvitem).returncode
    if a.cmd == 'apn': return run('apn.py', a.apn, *([a.csv] if a.csv else [])).returncode
    if a.cmd == 'pac': return run('pacwrite.py', a.src, a.dst, *a.replace).returncode
    if a.cmd == 'mockup': return run('mockup.py', *[x for x in (a.mmi_res, a.nvitem, a.user, a.out) if x]).returncode
    if a.cmd == 'images': return run('export_images.py', a.mmi_res, a.outdir).returncode
    if a.cmd == 'dump': return subprocess.run(['bash', os.path.join(HERE, 'dump_phone.sh'), a.mode]).returncode   # shell script, not Python
    return 0


if __name__ == '__main__':
    sys.exit(main())
