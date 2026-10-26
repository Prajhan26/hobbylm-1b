"""Hobby worker for the Hobby bar: keeps HobbyLM-1B + adapter loaded and runs requests over JSON lines.

  .venv/bin/python hobby/hobby_server.py r4
stdin, one JSON object per line:   {"type": "request", "text": "..."}   {"type": "answer", "text": "y"}
stdout, one JSON object per line:  ready | step | result | info | warn | confirm | ask | end | error
Every request finishes with exactly one end (kind: done | unknown | cancelled | off | stopped | error).
The same run() loop as hobby_demo.py: the model picks every action, the harness validates and executes it,
and calendar events still need an explicit yes.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
OUT = sys.stdout
sys.stdout = sys.stderr  # anything else that prints (libraries, warnings) stays off the protocol channel
import hobby_demo as H  # noqa: E402


def send(**msg):
    OUT.write(json.dumps(msg) + '\n')
    OUT.flush()


def read():
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return json.loads(line)


class Bar:
    """The Terminal interface from hobby_demo.py, spoken as JSON lines."""
    def step(self, seconds, act):
        send(type='step', seconds=round(seconds, 2), action=act)

    def result(self, res):
        send(type='result', text=res)

    def info(self, text):
        send(type='info', text=text)

    def warn(self, text):
        send(type='warn', text=text)

    def confirm(self, text):
        send(type='confirm', text=text)

    def ask(self, prompt):
        send(type='ask', prompt=prompt)
        while True:
            msg = read()
            if msg.get('type') == 'answer':
                return str(msg.get('text', ''))

    def end(self, kind, text):
        send(type='end', kind=kind, text=text)


def main():
    rnd = sys.argv[1] if len(sys.argv) > 1 else 'r4'
    h, mcp, ax = H.load(rnd)
    send(type='ready', accessibility=ax, calendar=H.CALENDAR_ENABLED)
    bar = Bar()
    try:
        while True:
            msg = read()
            if msg.get('type') != 'request' or not str(msg.get('text', '')).strip():
                continue
            try:
                H.run(h, mcp, msg['text'].strip(), bar)
            except EOFError:
                raise
            except Exception as e:  # one bad request must not take the warm model down
                traceback.print_exc()
                send(type='error', text=f'{type(e).__name__}: {e}')
                send(type='end', kind='error', text='That request failed. Hobby is ready for the next one.')  # every request ends with end
    except EOFError:
        pass
    finally:
        mcp.close()


if __name__ == '__main__':
    main()
