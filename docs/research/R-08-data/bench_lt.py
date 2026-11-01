import json, sys, time, urllib.request
pfile, ofile = sys.argv[1:3]
CODE = {'zh':'zh-Hans'}
def tr(q, src):
    body = json.dumps({'q': q, 'source': CODE.get(src, src), 'target': 'en', 'format': 'text'}).encode()
    req = urllib.request.Request('http://127.0.0.1:5000/translate', body, {'Content-Type': 'application/json'})
    s = time.perf_counter(); r = json.load(urllib.request.urlopen(req, timeout=300)); return r['translatedText'], time.perf_counter() - s
P = json.load(open(pfile)); res = []; warm = {}
for lang in ['zh','ja','de','fr','es','pt']:
    warm[lang] = [round(tr('Test.', lang)[1], 2) for _ in range(8)]   # 4 gunicorn workers load models lazily
    for p in [p for p in P if p['lang'] == lang]:
        for scope, txt in (('title', p['text'].split('\n')[0] if lang not in ('zh','ja') else None), ('full', p['text'])):
            if txt is None: continue
            out, d = tr(txt, lang); res.append(dict(id=p['id'], scope=scope, chars=len(txt), seconds=round(d, 3), output=out))
    print(lang, 'warm-up s', warm[lang], 'full s', [r['seconds'] for r in res if r['scope']=='full' and r['id'].startswith(lang)], flush=True)
json.dump(dict(provider='libretranslate', warmup_s=warm, results=res), open(ofile, 'w'), ensure_ascii=False, indent=1)
