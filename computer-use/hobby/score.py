"""Score held-out trials. Reference rule for a 'correct next action' (fixed before reading held-out results):
  app closed -> OPEN System Settings; checker says destination already selected -> DONE;
  destination visible in the sidebar -> CLICK destination; otherwise -> SCROLL toward it (full sidebar order below).
A rejected proposal is a model error, never a correct action.
"""
import os
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent import norm  # noqa: E402

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
RUNS = ROOT / 'data' / 'runs'
# Full sidebar order on this Mac, captured read-only before the trials (observations/dev-sidebar-*.txt)
ORDER = ['Sign in, with your Apple Account', 'Wi‑Fi', 'Bluetooth', 'Network', 'Battery', 'General', 'Accessibility', 'Appearance',
         'Apple Intelligence & Siri', 'Control Centre', 'Desktop & Dock', 'Displays', 'Screen Saver', 'Spotlight', 'Wallpaper',
         'Notifications', 'Sound', 'Focus', 'Screen Time', 'Lock Screen', 'Privacy & Security', 'Touch ID & Password', 'Users & Groups',
         'Internet Accounts', 'Game Center', 'iCloud', 'Wallet & Apple Pay', 'Keyboard', 'Trackpad', 'Printers & Scanners']
IDX = {norm(x): i for i, x in enumerate(ORDER)}


def reference(step: dict, dest: str) -> str:
    o = step['observation']
    if o['closed']:
        return 'OPEN System Settings'
    if step['checker_reached_before_action']:
        return 'DONE'
    vis = [t for _, t in o['sidebar']]
    if any(norm(t) == norm(dest) for t in vis):
        return f'CLICK {dest}'
    pos = [IDX[norm(t)] for t in vis if norm(t) in IDX]
    return 'SCROLL DOWN' if pos and IDX[norm(dest)] > max(pos) else 'SCROLL UP'


def model_action(step: dict) -> str:
    if step['harness']['validation'] != 'valid':
        return f'(rejected: {step["harness"]["validation"]})'
    t = step['action_text']
    return t


def main():
    trials = [json.loads((d / 'trial.json').read_text()) for d in sorted(RUNS.glob('held_out-*')) if (d / 'trial.json').exists()]
    rows, agg = [], {c: Counter() for c in ('A', 'B')}
    lat = {c: [] for c in ('A', 'B')}
    for r in trials:
        c, dest = r['condition'], r['task']['dest']
        a = agg[c]
        a['trials'] += 1
        a['completed'] += bool(r.get('fully_completed'))
        a['reached_destination'] += bool(r.get('checker_reached_final'))
        a['human_interventions'] += r.get('human_interventions', 0)
        a[f'stop:{r["stop"]}'] += 1
        a['seconds_total'] += r.get('seconds_total', 0)
        for s in r['steps']:
            ref = reference(s, dest)
            got = model_action(s)
            a['proposals'] += 1
            a['format_ok'] += bool(s['parsed']['format_ok'])
            a[f'validation:{s["harness"]["validation"]}'] += 1
            a['correct_next_action'] += norm(got) == norm(ref)
            a['reference_' + ref.split()[0]] += 1
            a['correct_' + ref.split()[0]] += norm(got) == norm(ref)
            lat[c].append((s['model']['total_tokens'], s['model']['seconds']))
        said_done = r.get('model_said_done')
        a['completion_recognised'] += said_done and r.get('checker_reached_final')
        a['false_done'] += bool(said_done and not r.get('checker_reached_final'))
        a['missed_completion'] += r['stop'] == 'missed_completion'
        rows.append({'task': r['task']['id'], 'dest': dest, 'start': r['task']['start'], 'condition': c, 'stop': r['stop'],
                     'completed': r.get('fully_completed'), 'reached': r.get('checker_reached_final'), 'proposals': len(r['steps']),
                     'executed': r.get('executed'), 'seconds': round(r.get('seconds_total', 0), 1),
                     'actions': [model_action(s) + ('' if norm(model_action(s)) != norm(reference(s, dest)) else ' ✓') for s in r['steps']],
                     'references': [reference(s, dest) for s in r['steps']]})
    for c in ('A', 'B'):
        if lat[c]:
            toks = [t for t, _ in lat[c]]
            secs = [s for _, s in lat[c]]
            agg[c]['max_tokens_per_call'] = max(toks)
            agg[c]['mean_tokens_per_call'] = round(sum(toks) / len(toks))
            agg[c]['mean_model_seconds_per_call'] = round(sum(secs) / len(secs), 2)
    out = {'reference_rule': __doc__.strip(), 'by_condition': {c: dict(v) for c, v in agg.items()}, 'trials': rows}
    (ROOT / 'data' / 'heldout-score.json').write_text(json.dumps(out, indent=1, ensure_ascii=False) + '\n')
    for c, v in agg.items():
        print(c, dict(v))
    for row in rows:
        print(row['task'], row['condition'], row['dest'], row['start'], row['stop'], 'completed' if row['completed'] else '-', row['actions'])


if __name__ == '__main__':
    main()
