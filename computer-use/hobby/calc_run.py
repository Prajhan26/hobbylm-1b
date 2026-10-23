"""Calculator typing test: HobbyLM turns a spoken-style request into Calculator keystrokes and decides when it is done.

  .venv-mlx-release/bin/python backend/capability/macos_agent/calc_run.py --set dev|held_out [--only N]
MODEL: every action (TYPE <keys> / CLEAR / DONE / UNKNOWN). HARNESS: opens + clears Calculator (setup), shows the display,
validates (only 0-9 . + - * / =; × ÷ − accepted as the same keys), types through macos-use. CHECKER: calc_checker reads the
display from the Accessibility API. Invalid actions are rejected and not retried.
"""
from __future__ import annotations

import os

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hobby_runtime import Hobby  # noqa: E402
from mcp_client import MCP, SERVER_COMMIT  # noqa: E402

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
WORK = ROOT / 'data'
STOP = WORK / 'STOP'
MAX_PROPOSALS, MAX_NEW, FMT = 6, 16, 'native'

SYSTEM = ("You operate the Calculator app on a Mac for the user. Each turn you see the calculator display and choose "
          "exactly ONE next action.\nAllowed actions:\n"
          "TYPE <keys>  (press calculator keys: digits, . + - * / =, e.g. TYPE 2+2=)\n"
          "CLEAR  (clear the display)\n"
          "DONE  (the display shows the answer to the user's request)\n"
          "UNKNOWN  (you cannot tell what to do)\n"
          "Let the calculator do the arithmetic. Reply with the action only.")
FEWSHOT = [  # numbers chosen to appear in no dev or held-out request
    ('Request: add 11 and 4\n\nScreen:\nApp: Calculator\nDisplay: 0\n\nNext action:', 'TYPE 11+4='),
    ('Request: add 11 and 4\n\nScreen:\nApp: Calculator\nDisplay: 15\n\nLast action: TYPE 11+4=. Result: display changed from 0 to 15.\n\nNext action:', 'DONE'),
    ('Request: subtract 2 from 8\n\nScreen:\nApp: Calculator\nDisplay: 0\n\nNext action:', 'TYPE 8-2='),
]
ACTION = re.compile(r'^\s*(?:(TYPE)\s+([0-9.+\-*/=×÷−xX ]*[0-9=])|(CLEAR|DONE|UNKNOWN)\b)(.*)$', re.I)
KEYS = re.compile(r'^[0-9.+\-*/=]+$')


def clean(d):
    return (d or '').replace('‎', '').replace('‏', '').strip()


def num(d):
    try:
        return float(clean(d).replace(',', ''))
    except ValueError:
        return None


def render(req, display, history):
    lines = [f'Request: {req}', '', 'Screen:', 'App: Calculator', f'Display: {display}']
    if history:
        h = history[-1]
        if len(history) > 1:
            lines += ['', 'Earlier actions: ' + '; '.join(x['action'] for x in history[-3:-1])]
        lines += ['' if len(history) == 1 else '', f'Last action: {h["action"]}. Result: {h["result"]}']
    return '\n'.join(lines + ['', 'Next action:'])


def messages(req, display, history):
    m = [{'role': 'system', 'content': SYSTEM}]
    for u, a in FEWSHOT:
        m += [{'role': 'user', 'content': u}, {'role': 'assistant', 'content': a}]
    return m + [{'role': 'user', 'content': render(req, display, history)}]


def parse(raw):
    """Read the action from the START of the first non-empty line; anything after it is dropped and flagged
    (rule fixed in dev, before held-out). Keys are never edited: 'TYPE 6+8=14' is typed as 6+8=14."""
    first = next((l for l in raw.splitlines() if l.strip()), '')
    m = ACTION.match(first)
    if not m:
        return {'format_ok': False, 'clean': False, 'first_line': first}
    trailing = m.group(4).strip()
    if m.group(1):
        return {'format_ok': True, 'clean': not trailing, 'kind': 'TYPE', 'arg': m.group(2).strip(), 'trailing': trailing, 'first_line': first}
    return {'format_ok': True, 'clean': trailing in ('', '.'), 'kind': m.group(3).upper(), 'arg': None, 'trailing': trailing, 'first_line': first}


def validate(p):
    if not p['format_ok']:
        return {'status': 'invalid_format'}
    if p['kind'] == 'TYPE':
        keys = re.sub(r'\s+', '', p['arg']).replace('×', '*').replace('÷', '/').replace('−', '-').replace('x', '*').replace('X', '*')
        if not KEYS.match(keys):
            return {'status': 'out_of_scope', 'reason': f'TYPE contains keys outside 0-9 . + - * / =: {p["arg"]!r}'}
        return {'status': 'valid', 'keys': keys}
    return {'status': 'valid'}


def check():
    return json.loads(subprocess.run([str(WORK / 'calc_checker')], capture_output=True, text=True, timeout=20).stdout)


def trial(h, mcp, req, answer):
    t0 = time.perf_counter()
    r = mcp.call('macos-use_open_application_and_traverse', {'identifier': 'Calculator'})
    pid = int(r['fields']['pid'])
    mcp.call('macos-use_press_key_and_traverse', {'pid': pid, 'keyName': 'Escape'})  # setup: clear
    if num(check()['display']) != 0:
        raise SystemExit('setup failed: display not 0')
    steps, history, stop = [], [], None
    for i in range(MAX_PROPOSALS):
        display = clean(check()['display'])
        reached = num(display) is not None and abs(num(display) - answer) < 1e-9
        msgs = messages(req, display, history)
        g = h.complete(msgs, FMT, MAX_NEW)
        p, rec = parse(g['raw']), None
        v = validate(p)
        action = (f'TYPE {v["keys"]}' if v['status'] == 'valid' and p['kind'] == 'TYPE' else p.get('kind') if p['format_ok'] else f'(unparseable: "{p["first_line"][:40]}")')
        rec = {'i': i, 'display_before': display, 'checker_reached_before_action': reached, 'prompt_user_turn': msgs[-1]['content'],
               'prompt_tokens': g['prompt_tokens'], 'output_tokens': g['output_tokens'], 'total_tokens': g['total_tokens'], 'seconds': g['seconds'],
               'raw': g['raw'], 'parsed': p, 'validation': v['status'], 'reason': v.get('reason'), 'action': action}
        steps.append(rec)
        if p['format_ok'] and p['kind'] in ('DONE', 'UNKNOWN'):
            stop = 'model_' + p['kind'].lower()
            break
        if reached:
            rec['blocked'] = 'answer already on the display; further actions not executed'
            stop = 'missed_completion'
            break
        if v['status'] == 'out_of_scope':
            stop = 'out_of_scope'
            break
        if history and history[-1]['no_change'] and history[-1]['action'] == action:
            stop = 'no_progress_loop'
            break
        if v['status'] != 'valid':
            history.append({'action': action, 'result': 'rejected (not an allowed action).', 'no_change': True})
            continue
        if STOP.exists():
            raise KeyboardInterrupt('STOP file')
        if p['kind'] == 'TYPE':
            mcp.call('macos-use_type_and_traverse', {'pid': pid, 'text': v['keys']})
        else:
            mcp.call('macos-use_press_key_and_traverse', {'pid': pid, 'keyName': 'Escape'})
        after = clean(check()['display'])
        rec['display_after'] = after
        history.append({'action': action, 'result': f'display changed from {display} to {after}.' if after != display else 'display did not change.',
                        'no_change': after == display})
    else:
        stop = 'max_proposals'
    final = clean(check()['display'])
    correct = num(final) is not None and abs(num(final) - answer) < 1e-9
    typed = [s['action'][5:] for s in steps if s['action'].startswith('TYPE ') and s['validation'] == 'valid']
    return {'request': req, 'answer': answer, 'stop': stop, 'final_display': final, 'final_correct': correct,
            'fully_completed': stop == 'model_done' and correct, 'model_said_done': stop == 'model_done',
            'typed_only_a_number': bool(typed) and all(re.fullmatch(r'[0-9.]+=?', k) for k in typed),
            'proposals': len(steps), 'seconds_total': time.perf_counter() - t0, 'steps': steps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', choices=['dev', 'held_out'], required=True)
    a = ap.parse_args()
    T = json.loads((WORK / 'frozen' / 'calc-tasks.json').read_text())
    src_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if a.set == 'held_out':
        fz = json.loads((WORK / 'frozen' / 'calc-prompt.json').read_text())
        if fz['calc_run_py_sha256'] != src_sha:
            raise SystemExit('calc_run.py changed after the prompt was frozen')
        items = [(c, q, ans) for c, xs in T['held_out'].items() for q, ans in xs]
    else:
        items = [('dev', q, ans) for q, ans in T['dev']]
    out = WORK / 'runs' / f'calc-{a.set}-{time.strftime("%Y%m%d-%H%M%S")}'
    out.mkdir(parents=True)
    h = Hobby(check_weights=True)
    mcp = MCP()
    results = []
    try:
        for cat, q, ans in items:
            r = trial(h, mcp, q, ans)
            r['category'] = cat
            results.append(r)
            print(cat, repr(q), '->', [s['action'] for s in r['steps']], '| display', r['final_display'], '| stop', r['stop'],
                  '| COMPLETED' if r['fully_completed'] else '', flush=True)
    except KeyboardInterrupt as e:
        print('interrupted', e)
    finally:
        mcp.close()
    meta = {'set': a.set, 'calc_run_py_sha256': src_sha, 'model_sha256': h.identity.get('model.safetensors'), 'prompt_format': FMT,
            'macos_use_commit': SERVER_COMMIT, 'results': results}
    (out / 'results.json').write_text(json.dumps(meta, indent=1, ensure_ascii=False) + '\n')
    print(out)


if __name__ == '__main__':
    main()
