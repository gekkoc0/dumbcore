#!/usr/bin/env python3
"""Сделать макет самодостаточным: встраивает data.js и все картинки в один HTML (base64), чтобы
он открывался из любого браузера по file:// без проблем с локальными скриптами/путями.

    work/.venv/bin/python -I tools/mockup_selfcontained.py [mockup_dir]
    open mockup/phone.html
"""
import sys, os, re, base64


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'mockup'
    html = open(os.path.join(out, 'index.html')).read()
    js = open(os.path.join(out, 'data.js')).read()

    # 1) встроить data.js прямо в HTML (убираем зависимость от внешнего скрипта)
    html = html.replace('<script src="data.js"></script>', '<script>\n' + js + '\n</script>')

    # 2) встроить картинки assets/* как data URL (base64) — и в src="…", и в JS-строках "assets/…"
    def repl(m):
        path = m.group(0)
        f = os.path.join(out, path)
        if not os.path.exists(f):
            return path
        ext = os.path.splitext(f)[1].lower()
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif',
                'bmp': 'image/bmp'}.get(ext[1:], 'application/octet-stream')
        return 'data:%s;base64,' % mime + base64.b64encode(open(f, 'rb').read()).decode()

    html = re.sub(r'assets/[A-Za-z0-9_.]+', repl, html)

    dest = os.path.join(out, 'phone.html')
    open(dest, 'w').write(html)
    print('%s: %d KB, самодостаточный (открой его)' % (dest, os.path.getsize(dest) // 1024))


if __name__ == '__main__':
    main()
