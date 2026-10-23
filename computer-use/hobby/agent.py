"""HobbyLM-controls-System-Settings harness: observation compaction, prompt, action parsing and validation.

Division of labour (kept separate in every log record):
  * MODEL: proposes one action per turn (OPEN / CLICK id / SCROLL UP|DOWN / DONE / UNKNOWN).
  * HARNESS: compacts the accessibility tree with a goal-independent rule, assigns short ids, parses and validates
    the proposal, executes valid ones through macos-use, enforces scope and stop rules.
  * CHECKER: independently decides whether the destination was reached (window title == destination).
The harness never looks at the goal when building observations or validating actions.

Compaction rule (goal-independent, fixed):
  - window title: text of the first visible [AXWindow (standard window)]
  - page text: first 4 visible AXStaticText items outside the sidebar, top-to-bottom (context only; not clickable)
  - sidebar: visible AXStaticText whose centre lies inside the [AXOutline (list)] "Sidebar" box, top-to-bottom -> ids s1..sN
  - buttons: visible toolbar [AXButton] "Back" and [AXMenuButton] "Forward" -> ids b1, b2
Content-area controls (switches, pop-ups, fields, other buttons) are never given ids, so they can never be clicked.
"""
from __future__ import annotations

import re
import unicodedata

LINE = re.compile(r'^\s*\[(AX\w+) \(([^)]*)\)\](?: "(.*?)")?(?: x:(-?\d+) y:(-?\d+))?(?: w:(\d+) h:(\d+))?( visible)?\s*$')
APP = 'System Settings'


def norm(s: str) -> str:
    """Normalise labels for comparison only (NBSP, non-breaking hyphen, case)."""
    s = unicodedata.normalize('NFKC', s).replace('‑', '-').replace(' ', ' ')
    return re.sub(r'\s+', ' ', s).strip().lower()


def parse_tree(text: str) -> list[dict]:
    els = []
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        role, sub, label, x, y, w, h, vis = m.groups()
        els.append({'role': role, 'sub': sub, 'text': label or '', 'x': int(x) if x else None, 'y': int(y) if y else None,
                    'w': int(w) if w else None, 'h': int(h) if h else None, 'visible': bool(vis)})
    return els


def compact(text: str, order: str = 'screen', seed: int = 0) -> dict:
    """order: 'screen' (top-to-bottom), 'reversed' or 'shuffled' (control-order sensitivity test only)."""
    els = parse_tree(text)
    vis = [e for e in els if e['visible'] and e['x'] is not None]
    title = next((e['text'] for e in vis if e['role'] == 'AXWindow' and e['sub'] == 'standard window'), None)
    sb = next((e for e in vis if e['role'] == 'AXOutline' and e['text'] == 'Sidebar' and e['w']), None)

    def in_sidebar(e):
        if not sb or e['w'] is None:
            return False
        cx, cy = e['x'] + e['w'] / 2, e['y'] + e['h'] / 2
        return sb['x'] <= cx <= sb['x'] + sb['w'] and sb['y'] <= cy <= sb['y'] + sb['h']

    texts = sorted([e for e in vis if e['role'] == 'AXStaticText' and e['text'] and e['w']], key=lambda e: (e['y'], e['x']))
    side = [e for e in texts if in_sidebar(e)]
    page = [e['text'] for e in texts if not in_sidebar(e)][:4]
    if order == 'reversed':
        side = side[::-1]
    elif order == 'shuffled':
        import random
        side = side[:]
        random.Random(seed).shuffle(side)
    buttons = [e for e in vis if e['role'] in ('AXButton', 'AXMenuButton') and e['text'] in ('Back', 'Forward') and e['w']]
    targets = {}
    for i, e in enumerate(side, 1):
        targets[f's{i}'] = e
    for i, e in enumerate(buttons, 1):
        targets[f'b{i}'] = e
    return {'title': title, 'page': page, 'sidebar': [(k, v['text']) for k, v in targets.items() if k[0] == 's'],
            'buttons': [(k, v['text']) for k, v in targets.items() if k[0] == 'b'], 'targets': targets,
            'has_sidebar': sb is not None}


def closed_state() -> dict:
    return {'title': None, 'page': [], 'sidebar': [], 'buttons': [], 'targets': {}, 'has_sidebar': False, 'closed': True}


def state_key(s: dict) -> tuple:
    return (s.get('closed', False), s['title'], tuple(t for _, t in s['sidebar']))


def describe_diff(prev: dict | None, cur: dict) -> str:
    """Goal-independent summary of what changed after the last action (condition B only)."""
    if prev is None:
        return ''
    if prev.get('closed') and not cur.get('closed'):
        return f'System Settings opened; window title is "{cur["title"]}".'
    parts = []
    if prev['title'] != cur['title']:
        parts.append(f'window title changed from "{prev["title"]}" to "{cur["title"]}"')
    a, b = [t for _, t in prev['sidebar']], [t for _, t in cur['sidebar']]
    new = [t for t in b if t not in a]
    gone = [t for t in a if t not in b]
    if new or gone:
        parts.append(f'sidebar now shows {len(new)} new item(s)' + (f' ({new[0]} … {new[-1]})' if new else '') +
                     f' and hides {len(gone)}')
    return ('; '.join(parts) + '.') if parts else 'nothing on the screen changed.'


SYSTEM = ("You operate the System Settings app on a Mac for the user. Each turn you see the current screen "
          "and choose exactly ONE next action.\n"
          "Allowed actions:\n"
          "OPEN System Settings  (launch the app)\n"
          "CLICK <id>  (click one listed item, e.g. CLICK s3)\n"
          "SCROLL DOWN  (show sidebar items further down)\n"
          "SCROLL UP  (show sidebar items further up)\n"
          "DONE  (the goal is already reached)\n"
          "UNKNOWN  (you cannot tell what to do)\n"
          "Reply with the action only.")


FEWSHOT_VARIANTS = {  # format demonstrations on tiny synthetic screens; no held-out destination is ever the answer
    'ids': [
        ('Goal: Open System Settings and navigate to Focus.\n\nScreen:\nSystem Settings is not open.\n\nNext action:', 'OPEN System Settings'),
        ('Goal: Open System Settings and navigate to Sound.\n\nScreen:\nApp: System Settings\nWindow title: Sound\n'
         'Sidebar (visible part):\ns1 General\ns2 Focus\ns3 Sound\ns4 Screen Time\nButtons: b1 Back, b2 Forward\n\nNext action:', 'DONE'),
        ('Goal: Open System Settings and navigate to Screen Time.\n\nScreen:\nApp: System Settings\nWindow title: General\n'
         'Sidebar (visible part):\ns1 Screen Time\ns2 Sound\ns3 General\ns4 Focus\nButtons: b1 Back, b2 Forward\n\nNext action:', 'CLICK s1'),
        ('Goal: Open System Settings and navigate to Focus.\n\nScreen:\nApp: System Settings\nWindow title: Sound\n'
         'Sidebar (visible part):\ns1 General\ns2 Sound\ns3 Screen Time\ns4 Focus\nButtons: b1 Back, b2 Forward\n\nNext action:', 'CLICK s4'),
        ('Goal: Open System Settings and navigate to Screen Time.\n\nScreen:\nApp: System Settings\nWindow title: Sound\n'
         'Sidebar (visible part):\ns1 General\ns2 Sound\ns3 Focus\nButtons: b1 Back, b2 Forward\n\nNext action:', 'SCROLL DOWN'),
    ],
}
import re as _re


def _to_labels(u: str, a: str) -> tuple[str, str]:
    names = dict(_re.findall(r'^([sb]\d+) (.+)$', u, _re.M))
    u = _re.sub(r'^s\d+ (.+)$', r'- \1', u, flags=_re.M).replace('Buttons: b1 Back, b2 Forward', 'Buttons: Back, Forward')
    if a.startswith('CLICK '):
        a = 'CLICK ' + names[a.split()[1]]
    return u, a


FEWSHOT_VARIANTS['labels'] = [_to_labels(u, a) for u, a in FEWSHOT_VARIANTS['ids']]


def messages(goal: str, s: dict, history: list[dict], condition: str, fewshot: str | None) -> list[dict]:
    targets = 'labels' if fewshot == 'labels' else 'ids'
    msgs = [{'role': 'system', 'content': SYSTEM if targets == 'ids' else SYSTEM.replace('CLICK <id>  (click one listed item, e.g. CLICK s3)', 'CLICK <name>  (click one listed item by its exact name)')}]
    if fewshot:
        for u, a in FEWSHOT_VARIANTS[fewshot]:
            msgs += [{'role': 'user', 'content': u}, {'role': 'assistant', 'content': a}]
    msgs.append({'role': 'user', 'content': render_user(goal, s, history, condition, targets)})
    return msgs


def render_user(goal: str, s: dict, history: list[dict], condition: str, targets: str = 'ids') -> str:
    lines = [f'Goal: {goal}', '', 'Screen:']
    if s.get('closed'):
        lines.append('System Settings is not open.')
    else:
        lines.append(f'App: {APP}')
        lines.append(f'Window title: {s["title"]}')
        if s['page']:
            lines.append('Page text: ' + ' | '.join(s['page']))
        lines.append('Sidebar (visible part):')
        lines += [(f'{k} {t}' if targets == 'ids' else f'- {t}') for k, t in s['sidebar']] or ['(none)']
        if s['buttons']:
            lines.append('Buttons: ' + ', '.join((f'{k} {t}' if targets == 'ids' else t) for k, t in s['buttons']))
    recent = history[-3:]
    if recent:
        lines.append('')
        if condition == 'A':
            lines.append('Previous actions: ' + '; '.join(h['action_text'] for h in recent))
        else:
            last = recent[-1]
            if len(recent) > 1:
                lines.append('Earlier actions: ' + '; '.join(h['action_text'] for h in recent[:-1]))
            lines.append(f'Last action: {last["action_text"]}. Result: {last["result_text"]}')
    lines += ['', 'Next action:']
    return '\n'.join(lines)


ACTION = re.compile(r'^\s*(OPEN\s+(.+?)|CLICK\s+(.+?)|SCROLL\s+(UP|DOWN)|DONE|UNKNOWN)\s*\.?\s*$', re.I)


def parse_action(raw: str) -> dict:
    """Parse the FIRST non-empty line of the raw output. Formatting is judged here, before any validity check."""
    first = next((l for l in raw.splitlines() if l.strip()), '')
    m = ACTION.match(first)
    if not m:
        return {'format_ok': False, 'first_line': first}
    word = m.group(1).split()[0].upper()
    if word == 'OPEN':
        return {'format_ok': True, 'kind': 'OPEN', 'arg': m.group(2).strip().strip('"\''), 'first_line': first}
    if word == 'CLICK':
        a = m.group(3).strip().strip('"\'')
        return {'format_ok': True, 'kind': 'CLICK', 'arg': a.lower() if re.fullmatch(r'[A-Za-z]\d+', a) else a, 'first_line': first}
    if word == 'SCROLL':
        return {'format_ok': True, 'kind': 'SCROLL', 'arg': m.group(4).upper(), 'first_line': first}
    return {'format_ok': True, 'kind': word, 'arg': None, 'first_line': first}


def validate(p: dict, s: dict) -> dict:
    """Returns {'status': 'valid' | 'invalid_format' | 'invalid_target' | 'out_of_scope' | 'invalid_state', ...}."""
    if not p['format_ok']:
        return {'status': 'invalid_format', 'reason': 'not one of the allowed actions'}
    k = p['kind']
    if k == 'OPEN':
        if norm(p['arg']) != norm(APP):
            return {'status': 'out_of_scope', 'reason': f'OPEN of "{p["arg"]}" is outside the allowed app'}
        if not s.get('closed'):
            return {'status': 'invalid_state', 'reason': 'System Settings is already open'}
        return {'status': 'valid'}
    if s.get('closed') and k in ('CLICK', 'SCROLL'):
        return {'status': 'invalid_state', 'reason': 'System Settings is not open'}
    if k == 'CLICK':
        if p['arg'] in s['targets']:
            return {'status': 'valid', 'target': s['targets'][p['arg']], 'target_id': p['arg']}
        hits = [k for k, e in s['targets'].items() if norm(e['text']) == norm(p['arg'])]
        if len(hits) == 1:  # exact name of exactly one listed control (no fuzzy matching)
            return {'status': 'valid', 'target': s['targets'][hits[0]], 'target_id': hits[0]}
        return {'status': 'invalid_target', 'reason': f'"{p["arg"]}" is not a listed item on the current screen'}
    if k == 'SCROLL' and not s['has_sidebar']:
        return {'status': 'invalid_state', 'reason': 'no sidebar to scroll'}
    return {'status': 'valid'}


def action_text(p: dict, s: dict) -> str:
    if not p.get('format_ok'):
        return f'(unparseable: "{p["first_line"][:40]}")'
    if p['kind'] == 'CLICK':
        v = validate(p, s)
        if v['status'] == 'valid':
            return f'CLICK {v["target"]["text"]}'
        return f'CLICK {p["arg"]} (not on screen)'
    return ' '.join(x for x in (p['kind'], p.get('arg')) if x)
