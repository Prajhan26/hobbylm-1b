"""Regex baseline for the Calculator test (written before any model call). Digits only; no word numbers or word problems."""
import json
import re
import sys
from pathlib import Path

N = r'(\d+(?:\.\d+)?)'
RULES = [
    (rf'subtract {N} from {N}', lambda a, b: f'{b}-{a}='),
    (rf'take {N} away from {N}', lambda a, b: f'{b}-{a}='),
    (rf'{N} less than {N}', lambda a, b: f'{b}-{a}='),
    (rf'how much bigger is {N} than {N}', lambda a, b: f'{a}-{b}='),
    (rf'multiply {N} by {N}', lambda a, b: f'{a}*{b}='),
    (rf'(?:add|sum of) {N} and {N}', lambda a, b: f'{a}+{b}='),
    (rf'{N} plus {N}', lambda a, b: f'{a}+{b}='),
    (rf'{N} minus {N}', lambda a, b: f'{a}-{b}='),
    (rf'{N} times {N}', lambda a, b: f'{a}*{b}='),
    (rf'{N} divided by {N}', lambda a, b: f'{a}/{b}='),
]


def parse(text: str) -> str | None:
    t = text.lower()
    for pat, f in RULES:
        m = re.search(pat, t)
        if m:
            return f(*m.groups())
    return None


def value(keys: str | None):
    if not keys:
        return None
    return eval(keys.rstrip('='), {'__builtins__': {}})  # keys come only from the patterns above


if __name__ == '__main__':
    T = json.loads((Path(__file__).resolve().parents[1] / 'data/frozen/calc-tasks.json').read_text())
    out = {}
    for cat, items in T['held_out'].items():
        ok = sum(value(parse(q)) == a for q, a in items)
        out[cat] = f'{ok}/{len(items)}'
        for q, a in items:
            print(cat, repr(q), parse(q), value(parse(q)) == a)
    print(out)
    if '--save' in sys.argv:
        (Path(__file__).resolve().parents[1] / 'data/calc-regex-baseline.json').write_text(json.dumps(out, indent=1) + '\n')
