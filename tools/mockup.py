#!/usr/bin/env python3
"""Build an interactive phone mock-up (HTML) from the firmware's own resources. Not an emulator: windows are drawn
by the page, but every picture, icon, wallpaper and string comes from mmi_res, and the main menu order from NV 680.

    python3 -I tools/mockup.py <mmi_res.bin> <nvitem.bin> <user.bin> [out_dir]
    open out_dir/index.html          (default out_dir: mockup/ in the project root)

mmi_res, nvitem and user (EXEC_USER_IMAGE / user.bin from a phone backup, starts with "DHTB") must come from the
same firmware build. The menu item table is located automatically in the user image, so any build works.
Use a modified mmi_res (from sresedit.py / ttf2sfon.py) to see your own icons and texts in the mock-up.
"""
import os, sys, json, io, glob, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from sres import Sres
from imgcodec import decode_any, png_bytes
from sresedit import cscs_names, languages
from nvmenu import read_menu
import sjpg

DEV_EXT = os.path.join(ROOT, 'work/ext/official_3210_11.00.17.00_QB_16ICN18HK00/')   # developer default only
USER_BASE = 0x88000000            # the user image file (with its 0x200-byte DHTB header) is loaded here; code at +0x200


def _menu_record(d, o):
    """One s_mainmenu_item_data entry {code, text id, image A, image B, handler, 0}: valid, empty or neither."""
    e = struct.unpack_from('<6I', d, o)
    if not any(e):
        return 'empty'
    if (0 < e[0] < 0x40 and e[1] >> 24 == 0x40 and e[2] >> 24 == 0x40 and e[3] >> 24 == 0x40 and e[5] == 0
            and (e[4] == 0 or USER_BASE <= e[4] < USER_BASE + len(d))):
        return 'item'
    return None


def find_menu_table(d):
    """Locate s_mainmenu_item_data (2 styles x 50 x 24 bytes) by its shape: 100 records, each an item or empty,
    at least 20 items, the first one an item. Returns the file offset or None."""
    for o in range(0, len(d) - 100 * 24, 4):
        if d[o + 7] != 0x40 or d[o + 11] != 0x40 or d[o + 15] != 0x40 or _menu_record(d, o) != 'item':
            continue
        kinds = [_menu_record(d, o + k * 24) for k in range(100)]
        if None not in kinds and kinds.count('item') >= 20:
            return o
    return None


def menu_table(user_path):
    """s_mainmenu_item_data: 2 styles x 50 x {code, text id, image A, image B, handler, 0}.
    Style 0 (grid): A = 76x76 icon, B = 76x76 selection ring. Style 1 (list): A = 240x180 backdrop, B = 160x160 icon."""
    d = open(user_path, 'rb').read()
    if d[:4] != b'DHTB':
        sys.exit(f'{user_path}: not a user image (no DHTB header)')
    o = find_menu_table(d)
    if o is None:
        sys.exit(f'{user_path}: main menu item table not found')
    styles = []
    for style in range(2):
        items = {}
        for k in range(50):
            e = struct.unpack_from('<6I', d, o + style * 0x4b0 + k * 0x18)
            if e[0]:
                items[e[0]] = dict(text=e[1], icon=e[2], frame=e[3])
        styles.append(items)
    print(f'menu table at {USER_BASE + o:#x} ({len(styles[0])} + {len(styles[1])} items)')
    return styles


def main(argv):
    if len(argv) >= 4:
        res, nv, user = argv[1:4]
        out = argv[4] if len(argv) > 4 else os.path.join(ROOT, 'mockup')
    elif os.path.isdir(DEV_EXT):                     # developer checkout: official 11.00 HK files
        res, nv, user = DEV_EXT + 'mmi_res_240X320_QB.bin', glob.glob(DEV_EXT + '*nvitem*.bin')[0], DEV_EXT + 'EXEC_USER_IMAGE.bin'
        out = os.path.join(ROOT, 'mockup')
    else:
        sys.exit(__doc__)
    adir = os.path.join(out, 'assets')
    os.makedirs(adir, exist_ok=True)
    s = Sres(res)
    M = {m['index']: m for m in s.modules}
    langs = languages(s)
    RU = langs.index('Russian') if 'Russian' in langs else 0
    names = cscs_names(s)

    def blob(rid):
        mod, idx = (rid >> 16) & 0xff, (rid & 0xffff) - 1
        b = s.blobs(M[mod], 0)[idx]
        return s.d[b['off']:b['off'] + b['size']]

    def save_img(rid, fname):
        raw = blob(rid)
        if raw[:4] == b'SJPG':
            open(os.path.join(adir, fname + '.jpg'), 'wb').write(sjpg.to_jpeg(raw)[0])
            return f'assets/{fname}.jpg'
        if raw[:2] == b'BM':
            open(os.path.join(adir, fname + '.bmp'), 'wb').write(raw)
            return f'assets/{fname}.bmp'
        if raw[:4] == b'SGIF':                       # animated GIF wallpaper: 12-byte wrapper + GIF file (resenc.sgif_wrap)
            open(os.path.join(adir, fname + '.gif'), 'wb').write(raw[12:])
            return f'assets/{fname}.gif'
        r = decode_any(raw)
        if not r:
            return None
        open(os.path.join(adir, fname + '.png'), 'wb').write(png_bytes(*r))
        return f'assets/{fname}.png'

    def named(n, fname=None):
        t, mod, idx = names[n]
        return save_img(0x40000000 | mod << 16 | (idx + 1), fname or n.lower())

    def text(rid, L=None):
        mod, idx = (rid >> 16) & 0xff, (rid & 0xffff) - 1
        return s.string_at(s.texts(M[mod])[RU if L is None else L][idx])

    def text_ix(mod, idx, L=None):
        return s.string_at(s.texts(M[mod])[RU if L is None else L][idx])

    data = {'source': os.path.basename(res), 'lang': langs[RU] if langs else '?'}
    # --- main menu: order from NV 680, meaning from the item table in USER
    ng, nl, grid, lst = read_menu(nv)
    styles = menu_table(user)
    items = []
    for code in sorted(set(styles[0]) | set(styles[1])):
        e0, e1 = styles[0].get(code), styles[1].get(code)
        items.append(dict(code=code, ru=text((e0 or e1)['text']), en=text((e0 or e1)['text'], 0),
                          icon=save_img(e0['icon'], f'menu_{code:02x}') if e0 else None,
                          big=save_img(e1['frame'], f'menu_big_{code:02x}') if e1 else None))   # style 1: frame = 160x160 icon
    data['menu'] = dict(items=items, grid=[c for c in grid[:ng] if c], list=[c for c in lst[:nl] if c])
    data['menu_frame'] = save_img(next(iter(styles[0].values()))['frame'], 'menu_frame')
    data['list_bg'] = save_img(next(iter(styles[1].values()))['icon'], 'menu_list_bg')    # style 1: icon = 240x180 backdrop
    # --- idle screen pieces
    wall = [save_img(0x40270001 + i, f'wallpaper_{i + 1}') for i in range(3)]
    data['wallpapers'] = wall
    data['time_digits'] = [named(f'IMAGE_IDLE_TIME_{d}') for d in range(10)]
    data['time_colon'] = named('IMAGE_IDLE_TIME_COLON')
    data['battery'] = [named(f'IMAGE_IDLE_TITLE_ICON_BATTERY{i}') for i in range(11)]
    data['signal'] = [named(f'IMAGE_IDLE_TITLE_ICON_SIGNAL{i}_AND_T') for i in range(1, 7)]
    data['statusbar'] = named('IMAGE_IDLE_STATUS_BAR')
    data['mid_softkey'] = named('IMAGE_IDLE_MIDDLE_SOFTKEY_ICON')
    data['selected_bar'] = named('IMAGE_COMMON_SELECTED_BAR')
    # --- strings. Text numbers differ between builds, so each one is found by its English text in module 0, taking the
    # match closest to its number in 11.00 HK (where they were found with sresedit.py --find); day/month names as a run.
    keys = dict(menu=(13, 'Menu'), back=(17, 'Back'), select=(15, 'Select'), contacts=(4, 'Contacts'),
                no_service=(8, 'No service'), options=(24, 'Options'), equal=(26, 'Equal'), clear=(3616, 'Clear'),
                empty=(3069, '<Empty List>'), no_record=(2918, 'No record'), turn_on=(3655, 'Turn on'),
                turn_off=(3656, 'Turn off'), today=(198, 'Today'),
                alarm_empty=(3653, 'Your alarms will show up here.Create one now.'), calendar=(3627, 'Calendar'),
                calculator=(3682, 'Calculator'), torch=(2970, 'Torch'), recorder=(2912, 'Recorder'),
                profiles=(3617, 'Profiles'), display=(2907, 'Display'), call_set=(2908, 'Call settings'),
                phone_set=(3681, 'Phone settings'), security=(3526, 'Security'), connectivity=(3691, 'Connectivity'),
                extras=(3644, 'Extras'))
    EN = 0
    english = [s.string_at(o) for o in s.texts(M[0])[EN]]
    def find(old, text):
        hits = [i for i, t in enumerate(english) if t == text]
        return min(hits, key=lambda i: abs(i - old)) if hits else old
    def find_run(first, second, old):
        hits = [i for i in range(len(english) - 2) if english[i] == first and english[i + 1] == second]
        return min(hits, key=lambda i: abs(i - old)) if hits else old
    idx = {k: find(o, t) for k, (o, t) in keys.items()}
    lists = dict(wdays=(find_run('Sun', 'Mon', 226), 7), months=(find_run('January', 'Febrary', 3719)
                 if 'Febrary' in english else find_run('January', 'February', 3719), 12))
    def strings(L):
        d = {k: text_ix(0, i, L) for k, i in idx.items()}
        d.update({k: [text_ix(0, a + j, L) for j in range(n)] for k, (a, n) in lists.items()})
        return d
    data['str'] = {'ru': strings(None), 'en': strings(0)}
    # --- pictures for the simple apps
    data['img'] = {k: named(n) for k, n in dict(
        torch='IMAGE_PRIMO_TORCH', set_profiles='IMAGE_SECMENU_ICON_SET_PROFILES', set_display='IMAGE_SECMENU_ICON_SET_DISPLAY',
        set_call='IMAGE_SECMENU_ICON_SET_CALL', set_phone='IMAGE_SECMENU_ICON_SET_PHONE',
        set_security='IMAGE_SECMENU_ICON_SET_SECURITY', set_link='IMAGE_SECMENU_ICON_SET_LINK',
        radio_on='IMAGE_CONTROL_LIST_RADIO_SELECTED_ICON', radio_off='IMAGE_CONTROL_LIST_RADIO_UNSELECTED_ICON').items()}
    # --- soft key / status icons cut from frames the firmware drew in the emulator (tools/mockup_ui, see docs/emulator.md)
    import shutil
    data['ui'] = {}
    for f in sorted(glob.glob(os.path.join(HERE, 'mockup_ui', '*.png'))):
        n = os.path.basename(f)[:-4]
        shutil.copy(f, os.path.join(adir, 'ui_' + n + '.png'))
        data['ui'][n] = f'assets/ui_{n}.png'
    open(os.path.join(out, 'data.js'), 'w').write('window.PHONE = ' + json.dumps(data, ensure_ascii=False, indent=1) + ';\n')
    import shutil
    shutil.copy(os.path.join(HERE, 'mockup_template.html'), os.path.join(out, 'index.html'))   # always the current template
    for f in ('mockup_phone.css', 'mockup_phone.js'):                                          # общий «телефон» (использует и студия)
        shutil.copy2(os.path.join(HERE, f), os.path.join(out, f))
    print(f'{out}: {len(items)} menu items ({len(data["menu"]["grid"])} in the grid), {len(os.listdir(adir))} assets, '
          f'language {data["lang"]}; open {os.path.join(out, "index.html")}')


if __name__ == '__main__':
    main(sys.argv)
