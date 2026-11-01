import json, sys, time, resource, os
lang, pfile, ofile = sys.argv[1:4]
t0 = time.perf_counter()
import argostranslate.translate as tr
inst = tr.get_installed_languages()
src = next(l for l in inst if l.code == lang); en = next(l for l in inst if l.code == 'en')
t = src.get_translation(en)
t.translate('Test.')                      # warm-up: loads model + sentence splitter
load_s = time.perf_counter() - t0
res = []
for p in [p for p in json.load(open(pfile)) if p['lang'] == lang]:
    for scope, txt in (('title', p['text'].split('\n')[0] if lang not in ('zh','ja') else None), ('full', p['text'])):
        if txt is None: continue
        s = time.perf_counter(); out = t.translate(txt); d = time.perf_counter() - s
        res.append(dict(id=p['id'], scope=scope, chars=len(txt), seconds=round(d, 3), output=out))
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
json.dump(dict(provider='argos', lang=lang, load_and_warmup_s=round(load_s, 2), peak_rss_mb=round(peak_mb), results=res), open(ofile, 'w'), ensure_ascii=False, indent=1)
print(lang, 'load', round(load_s,1), 'peak MB', round(peak_mb), 'full s', [r['seconds'] for r in res if r['scope']=='full'])
