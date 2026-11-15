#!/usr/bin/env python3
"""Build modified resources (and optionally a .pac) from a phone backup and a list of edits - in one command.

    mod.py --res <mmi_res.bin> --res-out <new mmi_res.bin> [EDITS]                       # verified path
    mod.py --res … --res-out … --pac <base.pac> --out <mod.pac> [--nv <nv_fixed.bin>] [EDITS]   # .pac: not verified

EDITS:
  --icon NAME=file.png        replace an image (official cscs name or MODULE:INDEX), repeatable
  --color NAME=#RRGGBB        replace a colour, repeatable
  --text M:N[@Language]=str   replace a string, repeatable
  --font font.ttf             your TrueType font for Latin and Cyrillic
  --hide-menu 07,0b,1c        NOT VERIFIED ON A PHONE: hide main-menu items by rewriting NV 680 in the *fixed* NV; the
                              phone seems to read the menu from the *running* NV, so this may have no effect. Needs --nv
                              and --pac, and puts your fixed NV (IMEI, calibration) into the .pac.

The resource file from a backup is cut to its real data first (the partition dump is padded with 0xFF). The new
mmi_res is what `dumbcore.py write 0x90000004 <file>` puts on the phone - the only write path tested on real hardware.
Only unsigned partitions change (MMIRes, and NV with --hide-menu); signed code images are never touched.
Needs Pillow. Everything is local.
"""
import sys, os, subprocess, tempfile, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nvmenu import read_menu
from nvmenu_write import write_menu
from sres import Sres


def run(tool, *args):
    print('$', tool, ' '.join(args))
    subprocess.run([sys.executable, '-I', os.path.join(HERE, tool), *args], check=True)


def trimmed(path, tmp):
    """Return a copy of a resource file without the 0xFF padding after its last section (or the file itself)."""
    s = Sres(path)
    end = max(o + n for _, o, n in s.sections)
    if end == len(s.d):
        return path
    tail = s.d[end:]
    if tail.count(0xff) != len(tail):
        sys.exit(f'{path}: {len(tail)} bytes after the last section are not 0xFF padding - refusing to guess')
    out = os.path.join(tmp, 'res_trimmed.bin')
    open(out, 'wb').write(s.d[:end])
    print(f'resources cut to their data: {end} bytes ({len(tail)} bytes of padding removed)')
    return out


def main():
    ap = argparse.ArgumentParser(description='DumbCore: modified resources (and .pac) from a backup and edits')
    ap.add_argument('--res', required=True, help='mmi_res.bin from your backup (or official, same build as the phone)')
    ap.add_argument('--res-out', required=True, help='new mmi_res.bin to write with `dumbcore.py write 0x90000004`')
    ap.add_argument('--pac', help='base .pac of the same software version (only to build a .pac - not verified)')
    ap.add_argument('--out', help='output .pac (with --pac)')
    ap.add_argument('--nv', help='your nv_fixed.bin from the backup (only with --hide-menu)')
    ap.add_argument('--hide-menu', help='NOT VERIFIED: menu codes to hide, hex, comma separated')
    ap.add_argument('--icon', action='append', default=[])
    ap.add_argument('--color', action='append', default=[])
    ap.add_argument('--text', action='append', default=[])
    ap.add_argument('--font')
    ap.add_argument('--verify', action='store_true', help='check the .pac checksums after building')
    a = ap.parse_args()
    if bool(a.pac) != bool(a.out):
        sys.exit('--pac and --out go together')
    if a.hide_menu and not (a.nv and a.pac):
        sys.exit('--hide-menu needs --nv (your nv_fixed.bin) and --pac/--out')

    tmp = tempfile.mkdtemp(prefix='dumbcore_mod_')
    res = trimmed(a.res, tmp)

    edits = a.icon + a.color + a.text
    if edits:
        nxt = os.path.join(tmp, 'res_edit.bin')
        run('sresedit.py', res, nxt, *edits)
        res = nxt
    if a.font:
        nxt = os.path.join(tmp, 'res_font.bin')
        run('ttf2sfon.py', res, nxt, a.font)
        res = nxt
    open(a.res_out, 'wb').write(open(res, 'rb').read())
    print(f'new resources: {a.res_out}  ->  python3 -I tools/dumbcore.py write 0x90000004 {a.res_out}')

    if a.pac:
        parts = [f'MMIRes={a.res_out}']
        if a.hide_menu:
            hidden = {int(x, 16) for x in a.hide_menu.split(',') if x.strip()}
            ng, nl, grid, lst = read_menu(a.nv)
            g = [c for c in grid[:ng] if c and c not in hidden]
            l = [c for c in lst[:nl] if c and c not in hidden]
            nv_new = os.path.join(tmp, 'nv_new.bin')
            open(nv_new, 'wb').write(write_menu(a.nv, g, l))
            parts.append(f'NV={nv_new}')
            print(f'menu (fixed NV, NOT VERIFIED): grid {len(g)}, list {len(l)} (hidden {len(hidden)})')
        run('pacwrite.py', a.pac, a.out, *parts)
        if a.verify:
            run('pacwrite.py', a.out, '--verify')
        print(f'.pac (flashing it with official tools is NOT VERIFIED): {a.out}')


if __name__ == '__main__':
    main()
