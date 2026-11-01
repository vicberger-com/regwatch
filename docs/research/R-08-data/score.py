import json, sys
from sacrebleu.metrics import CHRF, BLEU
P = {p['id']: p for p in json.load(open(sys.argv[1]))}
A = {(r['id'], r['scope']): r for l in 'zh ja de fr es pt'.split() for r in json.load(open(f'{sys.argv[2]}/argos_{l}.json'))['results']}
L = {(r['id'], r['scope']): r for r in json.load(open(f'{sys.argv[2]}/lt.json'))['results']}
chrf, bleu = CHRF(), BLEU(effective_order=True)
rows = []
for pid, p in P.items():
    ref = p['ref']; a = A[(pid,'full')]; l = L[(pid,'full')]
    rows.append(dict(id=pid, chars=a['chars'], a_s=a['seconds'], l_s=l['seconds'],
        a_chrf=round(chrf.sentence_score(a['output'], [ref]).score,1), l_chrf=round(chrf.sentence_score(l['output'], [ref]).score,1),
        a_bleu=round(bleu.sentence_score(a['output'], [ref]).score,1), same=a['output'].strip()==l['output'].strip()))
for r in rows: print(r)
for lang in 'zh ja de fr es pt'.split():
    ids = [i for i in P if P[i]['lang']==lang]
    refs = [[P[i]['ref'] for i in ids]]
    for name, D in (('argos',A),('lt',L)):
        hyp = [D[(i,'full')]['output'] for i in ids]
        print(lang, name, 'corpus chrF', round(CHRF().corpus_score(hyp, refs).score,1), 'BLEU', round(BLEU().corpus_score(hyp, refs).score,1),
              'sec total', round(sum(D[(i,'full')]['seconds'] for i in ids),2), 'chars', sum(len(P[i]['text']) for i in ids))
json.dump(rows, open(f'{sys.argv[2]}/scores.json','w'), indent=1)
