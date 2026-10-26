"""Offline checks on the Hobby bar worker protocol (hobby_server.py). No model, no screen actions.

Every request must finish with exactly one `end`, including one that raises, and the worker must keep serving
requests afterwards. The model and macos-use are replaced by stubs.
"""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import hobby_server as S  # noqa: E402

H = S.H


class StubMCP:
    def close(self):
        pass


def fake_run(h, mcp, req, io_):
    if req == 'boom':
        raise RuntimeError('model fell over')
    io_.step(0.1, 'UNKNOWN')
    io_.end('unknown', "I can't do that one offline.")


requests = ['boom', "what's the weather tomorrow", 'boom', 'boom', 'second']
H.load = lambda rnd: (None, StubMCP(), True)
H.run = fake_run
sys.stdin = io.StringIO(''.join(json.dumps({'type': 'request', 'text': r}) + '\n' for r in requests))
out = io.StringIO()
S.OUT = out
S.main()

msgs = [json.loads(line) for line in out.getvalue().splitlines()]
ends = [m for m in msgs if m['type'] == 'end']
checks = [
    ('ready first', msgs[0]['type'] == 'ready'),
    ('one end per request', len(ends) == len(requests)),
    ('failed request ends with kind=error', [e['kind'] for e in ends] == ['error', 'unknown', 'error', 'error', 'unknown']),
    ('error detail sent before its end', all(msgs[i - 1]['type'] == 'error' for i, m in enumerate(msgs) if m.get('kind') == 'error')),
    ('worker kept serving after errors', ends[-1]['kind'] == 'unknown'),
]
say = sys.__stdout__.write  # hobby_server sends print() to stderr to keep its protocol channel clean
for name, ok in checks:
    say(f'{"ok  " if ok else "FAIL"} {name}\n')
fails = sum(not ok for _, ok in checks)
say(f'ALL PASSED {len(checks)}/{len(checks)}\n' if not fails else f'{fails} FAILED\n')
sys.exit(1 if fails else 0)
