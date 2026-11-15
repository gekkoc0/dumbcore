#!/usr/bin/env python3
"""Build a source-module map of a code image from Ghidra's function export (ExportFuncs.java).

    modmap.py work/ghidra/user_funcs.jsonl image.bin base [out.json]

Levels per function:
  anchored  - references a string naming a source file (assert/log '__FILE__')
  inferred  - lies between two functions anchored to the same file (link order keeps a .c file contiguous)
  unknown   - neither
Directory of each file comes from full paths seen anywhere in the image ('PS/stack/las/...').
"""
import json, re, sys, collections

SRC_RE = re.compile(r'(?:^|[/\\])([\w.-]+\.(?:c|cpp|cc))$')
TOPS = ('PS', 'DAPS', 'RTOS', 'MS_Ref', 'MS_Customize', 'MS_MMI_Main', 'PARSER', 'Third-party',
        'chip_drv', 'common', 'BASE', 'CMMB', 'connectivity', 'external', 'Third_party')

# subsystem by directory (checked first), then by file-name prefix
DIR_RULES = [
    ('PS/stack', 'Стек связи (2G/3G/4G протоколы)'), ('PS/layer1', 'Стек связи (физ. уровень)'),
    ('PS/sdi', 'Стек связи (инфраструктура)'), ('PS/dsm', 'Стек связи (данные)'), ('PS/atc', 'AT-команды'),
    ('PS/', 'Стек связи (прочее)'), ('RTOS/', 'ОС (RTOS)'), ('MS_Ref/', 'Драйверы и сервисы платформы'),
    ('MS_Customize/', 'Настройки платформы'), ('MS_MMI_Main/', 'Интерфейс: приложения'),
    ('DAPS/', 'Сеть и данные (TCP/IP, HTTP, SSL, MMS…)'), ('PARSER/', 'Браузер и парсеры'),
    ('Third-party/', 'Сторонние библиотеки'), ('Third_party/', 'Сторонние библиотеки'),
    ('chip_drv/', 'Драйверы чипа'),
]
PREFIX_RULES = [
    (('drv_rf', 'calibration', 'lte_calibration', 'l1c_calibration', 'rf_'), 'Калибровки и радиочасть'),
    (('rr', 'mn', 'mm_', 'plm', 'mph', 'phhandle', 'mac_', 'l1c_', 'layer1', 'rxlev', 'gsm', 'tmlg',
      'dmwg', 'wnas', 'nas', 'wrlc', 'rlc', 'rlp', 'asm_', 'vsm', 'vbm', 'systeminfo', 'dataproc', 'adm_',
      'llc', 'sndcp', 'grr', 'wrr', 'lrr', 'pdcp', 'cc_', 'sm_', 'ss_', 'sms', 'cbs', 'l1_', 'lte', 'erm',
      'eps', 'emm', 'esm', 'ims_', 'volte', 'pGrrlp'), 'Стек связи (2G/3G/4G протоколы)'),
    (('pspi', 'papi', 'opera', 'nps_', 'odm', 'mockup', 'brotli', 'utf_string', 'session_manager',
      'text_input_client', 'type_manager', 'override_new', 'ockup'), 'Браузер Opera Mini'),
    (('gameloft', 'japp', 'java', 'jbed', 'jvm', 'kvm'), 'Игры и Java'),
    (('autotest', 'assert_test', 'datadump', 'diag', 'sio', 'log', 'trace', 'dump'), 'Отладка и диагностика'),
    (('asf', 'avi', 'mp4', 'libmp4', 'rootlibmp4', 'minimp4', 'wma', 'msaudio', 'mpeg4', 'h263', 'mjpg',
      'demux', 'media', 'track_mixer', 'pcm', 'sbc', 'dsp', 'codec', 'clone_codec', 'uplink', 'downlink',
      'resample', 'transsample', 'id3', 'digitalgain', 'lpc', 'entropydec', 'lowrate', 'wmf', 'cvs_',
      'arm_tone', 'user_vdec', 's3d', 'exif', 'alpha_res', 'img_res', 'jpeg_res', 'gif_res', 'access_stream',
      'p_unpack', 'h264', 'avi_mux'), 'Медиа и изображения'),
    (('ui_special', 'layer_blend', 'tft_hal', 'lcdc', 'display', 'disp'), 'Графика и дисплей'),
    (('pstm', 'der_', 'security', 'x509', 'pkcs'), 'Сжатие и криптография'),
    (('staffat', 'file_cache', 'tmpfile', 'block', 'pktalloc'), 'Файловые системы и память'),
    (('hci_', 'db_rda'), 'Bluetooth'),
    (('caf', 'window_parse', 'mainapp', 'stylesheet'), 'Интерфейс: GUI-библиотека'),
    (('usim', 'nfc', 'ldo'), 'Драйверы и сервисы платформы'),
    (('mmk', 'ctrl', 'gui', 'mmitheme', 'ui_layer', 'uilayer'), 'Интерфейс: GUI-библиотека'),
    (('spml',), 'Шрифты и текст (SPML)'),
    (('mmi',), 'Интерфейс: приложения'),
    (('atc',), 'AT-команды'),
    (('brw', 'browser', 'css', 'html', 'wbxml', 'xml'), 'Браузер и парсеры'),
    (('http', 'wsp', 'wtp', 'wtls', 'ssl', 'tcp', 'ip', 'udp', 'dns', 'dhcp', 'rtsp', 'rtp', 'rtcp', 'strm',
      'sntp', 'pdp', 'ims', 'sip', 'net', 'ppp', 'mbedtls', 'mms', 'smtp', 'pop', 'ftp', 'ota', 'dl'),
     'Сеть и данные (TCP/IP, HTTP, SSL, MMS…)'),
    (('fat', 'sfs', 'fs', 'udisk', 'sd', 'nand', 'nor', 'flash', 'efs'), 'Файловые системы и память'),
    (('rdabt', 'bt', 'obex', 'a2dp', 'hfp', 'avrcp'), 'Bluetooth'),
    (('drm',), 'DRM'),
    (('amr', 'armvb', 'player', 'mp3', 'aac', 'aud', 'audio', 'midi', 'wav', 'video', 'mp4', 'h264',
      'jpeg', 'jpg', 'png', 'gif', 'bmp', 'img', 'dc', 'isp', 'camera', 'dv', 'record'), 'Медиа и изображения'),
    (('unzip', 'zip', 'zlib', 'lz', 'gzip', 'inflate', 'md5', 'sha', 'aes', 'des', 'rsa', 'crc'),
     'Сжатие и криптография'),
    (('lcd', 'lcm', 'kpd', 'keypad', 'gpio', 'adc', 'chg', 'charge', 'pwm', 'i2c', 'spi', 'uart', 'usb',
      'dma', 'timer', 'rtc', 'pmu', 'clock', 'sim', 'vbc', 'rf'), 'Драйверы и сервисы платформы'),
    (('os', 'sci', 'tx', 'threadx', 'mem', 'heap', 'tasks', 'thread', 'osa'), 'ОС (RTOS)'),
]


def subsystem(src, dirn):
    if dirn:
        for pfx, name in DIR_RULES:
            if dirn.startswith(pfx):
                return name
    stem = src.lower()
    for prefixes, name in PREFIX_RULES:
        if stem.startswith(prefixes):
            return name
    return 'Не классифицировано'


def load_paths(image):
    d = open(image, 'rb').read()
    paths = {}
    for m in re.finditer(rb'([\w.-]+(?:[/\\][\w.-]+)+)[/\\]([\w.-]+\.(?:c|cpp|cc))\x00', d):
        parts = m.group(1).decode().replace('\\', '/').split('/')
        # keep the part from a known top-level dir on (whole path component match)
        for k, p in enumerate(parts):
            if p in TOPS:
                parts = parts[k:]
                break
        paths.setdefault(m.group(2).decode(), '/'.join(parts))
    return paths


def main():
    funcs_path, image, base = sys.argv[1], sys.argv[2], int(sys.argv[3], 0)
    out = sys.argv[4] if len(sys.argv) > 4 else None
    funcs = [json.loads(l) for l in open(funcs_path)]
    for f in funcs:
        f['addr'] = int(f['a'], 16)
        srcs = []
        for s in f['str']:
            m = SRC_RE.search(s.strip())
            if m:
                srcs.append(m.group(1))
        f['src'] = collections.Counter(srcs).most_common(1)[0][0] if srcs else None
    funcs.sort(key=lambda f: f['addr'])
    # inference by contiguity: unknown run between two anchors of the same file
    last_i, last_src = None, None
    for i, f in enumerate(funcs):
        if f['src']:
            if last_src == f['src'] and last_i is not None:
                for j in range(last_i + 1, i):
                    if not funcs[j]['src']:
                        funcs[j]['src_inf'] = f['src']
            last_i, last_src = i, f['src']
    paths = load_paths(image)
    total_b = sum(f['sz'] for f in funcs)
    lvl = collections.Counter()
    by_dir = collections.defaultdict(lambda: [0, 0, set()])
    for f in funcs:
        src = f['src'] or f.get('src_inf')
        k = 'anchored' if f['src'] else ('inferred' if src else 'unknown')
        lvl[k] += f['sz']
        lvl[k + '_n'] += 1
        if src:
            sub = subsystem(src, paths.get(src))
            f['sub'] = sub
            by_dir[sub][0] += 1
            by_dir[sub][1] += f['sz']
            by_dir[sub][2].add(src)
    print(f'functions {len(funcs)}, bytes in functions {total_b} (image {len(open(image,"rb").read())-0x200})')
    for k in ('anchored', 'inferred', 'unknown'):
        print(f'  {k:<9} {lvl[k+"_n"]:6d} funcs  {lvl[k]:9d} B  {100*lvl[k]/max(total_b,1):5.1f}%')
    print('by subsystem (attributed functions):')
    for top, (n, b, files) in sorted(by_dir.items(), key=lambda x: -x[1][1])[:40]:
        print(f'  {top:<42} {n:6d} funcs {b:9d} B {100*b/max(total_b,1):5.1f}%  {len(files):4d} files')
    if out:
        json.dump(dict(levels=lvl, by_dir={k: [v[0], v[1], sorted(v[2])] for k, v in by_dir.items()},
                       funcs=[dict(a=f['a'], n=f['n'], sz=f['sz'], src=f['src'] or f.get('src_inf'),
                                   sub=f.get('sub'), how='anchored' if f['src'] else ('inferred' if f.get('src_inf') else None))
                              for f in funcs]), open(out, 'w'))


if __name__ == '__main__':
    main()
