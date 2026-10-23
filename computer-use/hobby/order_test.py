"""Control-order sensitivity (offline, no screen actions): re-ask the frozen prompt for the FIRST decision of every
held-out trial that started with Settings open, using that trial's saved first observation, with the sidebar listed in
screen order, reversed, and shuffled (3 seeds). Reports whether the chosen action changes and whether it is correct.
"""
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent import compact, messages, norm, parse_action, validate  # noqa: E402
from hobby_runtime import Hobby  # noqa: E402
from run import FEWSHOT, FMT, MAX_NEW  # noqa: E402
from score import IDX  # noqa: E402

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
RUNS = ROOT / 'data' / 'runs'


def ref(s, dest):
    vis = [t for _, t in s['sidebar']]
    if any(norm(t) == norm(dest) for t in vis):
        return f'CLICK {dest}'
    pos = [IDX[norm(t)] for t in vis if norm(t) in IDX]
    return 'SCROLL DOWN' if pos and IDX[norm(dest)] > max(pos) else 'SCROLL UP'


h = Hobby(check_weights=False)
rows = []
for d in sorted(RUNS.glob('held_out-*-B-*')):
    r = json.loads((d / 'trial.json').read_text())
    if r['task']['start'] == 'closed' or not (d / 'obs_00.txt').exists():
        continue
    text = (d / 'obs_00.txt').read_text()
    dest = r['task']['dest']
    out = {}
    for order, seed in [('screen', 0), ('reversed', 0), ('shuffled', 1), ('shuffled', 2), ('shuffled', 3)]:
        s = compact(text, order, seed)
        g = h.complete(messages(f'Open System Settings and navigate to {dest}.', s, [], 'A', FEWSHOT), FMT, MAX_NEW)
        p = parse_action(g['raw'])
        v = validate(p, s)
        act = (f'CLICK {v["target"]["text"]}' if v['status'] == 'valid' and p['kind'] == 'CLICK' else
               (' '.join(x for x in (p.get('kind'), p.get('arg')) if x) if v['status'] == 'valid' else f'(rejected: {v["status"]})'))
        out[f'{order}{seed if order == "shuffled" else ""}'] = {'action': act, 'correct': norm(act) == norm(ref(s, dest))}
    rows.append({'task': r['task']['id'], 'dest': dest, 'reference': ref(compact(text), dest), 'decisions': out,
                 'all_same': len({v['action'] for v in out.values()}) == 1})
    print(r['task']['id'], dest, {k: v['action'] + (' ✓' if v['correct'] else '') for k, v in out.items()})
summary = {'trials': len(rows), 'decision_unchanged_across_orders': sum(x['all_same'] for x in rows),
           'correct_by_order': {k: sum(x['decisions'][k]['correct'] for x in rows) for k in (rows[0]['decisions'] if rows else {})}}
print(summary)
(ROOT / 'data' / 'order-test.json').write_text(json.dumps({'doc': __doc__.strip(), 'summary': summary, 'rows': rows}, indent=1, ensure_ascii=False) + '\n')
