#!/usr/bin/env python3
"""Check whether a Nokia 3210 4G backup looks like genuine HMD hardware/firmware. Pass/fail checks only - this
never prints an IMEI or serial number, and the full backup (dump full) stays on your machine; nothing is sent
anywhere.

    python3 -I tools/verify_phone.py <backup folder>
    python3 -I tools/verify_phone.py <backup folder> --efuse efuse.bin

What it checks (see docs/verify.md):
  - code images (boot0/boot1/kernel/user) are signed with one of the three known HMD keys, and the RSA
    signature actually verifies (not just "a signature is present")
  - IMEI items (5, 377) are present, 15 digits, pass the Luhn check digit, and differ from each other
  - the production record (PhaseCheck) is present and non-blank
  - --efuse only: the supplied file contains the SHA-256 of the known HMD boot key

The result describes the backup data. Inspect the enclosure and labels separately.
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dhtb

HMD_KEYS = {
    '684648205e903a2e080833aa318e2acf55221a9b8ad22223ed248cc8ad20353f': 'FDL1 / BOOT0',
    'f0bfca66503e56402575feed5fbb64e59055571958448df8dd434f1ca2fe0952': 'FDL2 / BOOT1',
    'a76802f9fef25c1c3f38d1ed8bfcc85057af033a6cc7cb818075b55fa6f2122b': 'KERNEL / USER',
}


def nv_items(path):
    f = open(path, 'rb').read(); i = 4; out = {}
    while i + 4 <= len(f):
        iid, n = struct.unpack_from('<HH', f, i)
        if iid & n == 0xffff or (iid == 0 and n == 0):
            break
        out[iid] = f[i + 4:i + 4 + n]; i += 4 + ((n + 3) & ~3)
    return out


def decode_imei(b):
    if (b[0] & 15) != 10:
        return None
    nib = [b[0] >> 4]
    for x in b[1:]:
        nib += [x & 15, x >> 4]
    return ''.join(str(n) for n in nib[:15]) if all(n < 10 for n in nib[:15]) else None


def luhn_ok(d):
    s = 0
    for k, ch in enumerate(reversed(d)):
        v = int(ch)
        if k % 2:
            v = v * 2 - 9 if v * 2 > 9 else v * 2
        s += v
    return s % 10 == 0


def check(label, ok, detail=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {label}' + (f'  ({detail})' if detail else ''))
    return ok


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    d = sys.argv[1]
    efuse_path = sys.argv[sys.argv.index('--efuse') + 1] if '--efuse' in sys.argv else None
    results = []

    print('Code images (signature + hash):')
    for name, fn in (('boot0', 'boot0.bin'), ('boot1', 'boot1.bin'), ('kernel', 'kernel.bin'), ('user', 'user.bin')):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            results.append(check(name, False, 'file not found')); continue
        try:
            r = dhtb.parse(open(p, 'rb').read())
        except Exception as e:
            results.append(check(name, False, f'parse error: {e}')); continue
        who = HMD_KEYS.get(r.get('key_hash'))
        ok = bool(who) and r.get('hash_ok') and r.get('sig_ok')
        results.append(check(name, ok, who or 'unknown key' if not r.get('signed') else 'signature invalid'
                              if not ok else who))

    print('\nNV (calibration / IMEI):')
    nvp = os.path.join(d, 'nv_fixed.bin')
    if os.path.exists(nvp):
        nv = nv_items(nvp)
        imeis = []
        for iid in (5, 377):
            raw = nv.get(iid)
            dnum = decode_imei(raw[:8]) if raw and len(raw) >= 8 else None
            ok = dnum is not None and luhn_ok(dnum)
            results.append(check(f'IMEI item {iid}: 15 digits + Luhn checksum', ok))
            if ok:
                imeis.append(dnum)
        if len(imeis) == 2:
            results.append(check('IMEI1 and IMEI2 differ', imeis[0] != imeis[1]))
        pc = os.path.join(d, 'phasecheck.bin')
        if os.path.exists(pc):
            data = open(pc, 'rb').read()
            results.append(check('production record (PhaseCheck) present', any(data) and data[:1] != b'\xff'))
        else:
            results.append(check('production record (PhaseCheck) present', False, 'file not found'))
    else:
        results.append(check('nv_fixed.bin', False, 'file not found - run dumbcore dump full'))

    if efuse_path:
        print('\neFuse key hash (from supplied file):')
        raw = open(efuse_path, 'rb').read()
        words = struct.unpack('<%dI' % (len(raw) // 4), raw)
        logical = words[0::2]                      # each eFuse word is read back as a duplicate pair
        root_key = b''.join(struct.pack('<I', x) for x in logical[3:11]).hex()
        who = HMD_KEYS.get(root_key)
        results.append(check('eFuse root-of-trust = a known HMD key hash', who == 'FDL1 / BOOT0', who or 'no match'))

    n_ok, n_tot = sum(results), len(results)
    print(f'\n{n_ok}/{n_tot} checks passed.')
    if n_ok == n_tot:
        print('The HMD firmware signatures and backup records passed the checks.')
    else:
        print('One or more checks failed - this does NOT by itself prove the device is a clone (a file could be')
        print('missing or truncated in this backup), but genuine phones normally pass every check above.')
    sys.exit(0 if n_ok == n_tot else 1)


if __name__ == '__main__':
    main()
