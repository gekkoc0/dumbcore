import sys, os, glob, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pacinfo import extract
fw, out = sys.argv[1], sys.argv[2]
for pac in sorted(glob.glob(os.path.join(fw, '*.pac'))):
    name = os.path.basename(pac)[:-4]
    p = extract(pac, os.path.join(out, name))
    print(f"## {name}  fw={p['fw']}")
    for e in p['entries']:
        if e['file'] and e['raw'][0]:
            d = open(os.path.join(out, name, e['file']), 'rb').read()
            print(f"   {e['id']:<11} {hex(e['raw'][6]):<11} {e['raw'][0]:>9}  {hashlib.md5(d).hexdigest()[:8]}  {e['file']}")
