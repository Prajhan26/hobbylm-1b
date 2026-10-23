"""Live runner: HobbyLM navigates System Settings through macos-use. One trial per call.

Usage (from repo root):
  .venv-mlx-release/bin/python backend/capability/macos_agent/run.py --task H01 --condition B [--set held_out]
Stop at any time: Ctrl-C, `touch work/macos-agent/STOP`, or Esc during an action (macos-use InputGuard).
Every model call, raw output, parse, validation, tool call and screenshot is written to work/macos-agent/runs/<run_id>/.
"""
from __future__ import annotations

import os

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent import APP, closed_state, compact, describe_diff, messages, norm, parse_action, state_key, validate, action_text  # noqa: E402
from hobby_runtime import Hobby  # noqa: E402
from mcp_client import MCP, SERVER_COMMIT  # noqa: E402

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
WORK = ROOT / 'data'
STOP = WORK / 'STOP'
FROZEN = WORK / 'frozen'
MAX_PROPOSALS = 10
MAX_NEW = 16
FMT, FEWSHOT = 'native', 'labels'
SCROLL_LINES = {'DOWN': -5, 'UP': 5}  # calibrated on this Mac: negative deltaY revealed lower sidebar items


def app_running() -> bool:
    return subprocess.run(['pgrep', '-x', APP], capture_output=True).returncode == 0


def quit_app():
    subprocess.run(['osascript', '-e', f'quit app "{APP}"'], capture_output=True)
    for _ in range(40):
        if not app_running():
            return
        time.sleep(0.25)
    raise SystemExit('System Settings did not quit')


class Trial:
    def __init__(self, task: dict, condition: str, hobby: Hobby, out: Path, prompt_sha: str):
        self.task, self.cond, self.h, self.out = task, condition, hobby, out
        self.goal = f'Open System Settings and navigate to {task["dest"]}.'
        self.mcp = MCP()
        self.pid = None
        self.steps: list[dict] = []
        self.prompt_sha = prompt_sha
        self.shot_n = 0

    def save_shot(self, res: dict, tag: str) -> str | None:
        src = res['fields'].get('screenshot') if res else None
        if src and Path(src).exists():
            self.shot_n += 1
            dst = self.out / f'{self.shot_n:02d}_{tag}.png'
            shutil.copy(src, dst)
            return dst.name
        return None

    def observe(self, tag: str) -> tuple[dict, dict | None]:
        if not app_running():
            return closed_state(), None
        if self.pid is None:
            self.pid = int(subprocess.run(['pgrep', '-x', APP], capture_output=True, text=True).stdout.split()[0])
        res = self.mcp.call('macos-use_refresh_traversal', {'pid': self.pid})
        (self.out / f'obs_{len(self.steps):02d}.txt').write_text(res['file_text'] or '')
        s = compact(res['file_text'] or '')
        s['dialog'] = 'dialog' in res['fields'] or '# dialog: AXSheet' in (res['file_text'] or '')
        s['shot'] = self.save_shot(res, tag)
        return s, res

    def setup(self):
        t = self.task
        quit_app()
        if t['start'] == 'closed':
            return
        r = self.mcp.call('macos-use_open_application_and_traverse', {'identifier': APP})
        self.pid = int(r['fields']['pid'])
        for scroll_after in (30, -30, None):  # harness setup: look, scroll to top, look, scroll to bottom, look
            s, _ = self.observe('setup')
            hit = [e for k, e in s['targets'].items() if k[0] == 's' and norm(e['text']) == norm(t['start_pane'])]
            if hit:
                e = hit[0]
                self.mcp.call('macos-use_click_and_traverse', {'pid': self.pid, 'x': e['x'], 'y': e['y'], 'width': e['w'], 'height': e['h']})
                break
            if scroll_after is None:
                raise SystemExit(f'setup failed: start pane {t["start_pane"]!r} not found in the sidebar')
            self.mcp.call('macos-use_scroll_and_traverse', {'pid': self.pid, 'x': 120, 'y': 450, 'deltaY': scroll_after})
        sb = 30 if t['start'] == 'pane_top' else -30
        self.mcp.call('macos-use_scroll_and_traverse', {'pid': self.pid, 'x': 120, 'y': 450, 'deltaY': sb})
        s, _ = self.observe('setup_done')
        c = self.check()
        if not any(norm(x) == norm(t['start_pane']) for x in c['selected']):
            raise SystemExit(f'setup failed: selected {c["selected"]!r} != {t["start_pane"]!r}')

    def check(self) -> dict:
        out = subprocess.run([str(WORK / 'checker')], capture_output=True, text=True, timeout=20).stdout
        return json.loads(out)

    def reached(self, s: dict | None = None) -> bool:
        c = self.check()
        return c['running'] and any(norm(x) == norm(self.task['dest']) for x in c['selected'])

    def execute(self, p: dict, v: dict, s: dict) -> dict:
        if STOP.exists():
            raise KeyboardInterrupt('STOP file')
        if p['kind'] == 'OPEN':
            r = self.mcp.call('macos-use_open_application_and_traverse', {'identifier': APP})
            self.pid = int(r['fields'].get('pid', 0)) or None
            call = {'tool': 'open_application_and_traverse', 'args': {'identifier': APP}}
        elif p['kind'] == 'CLICK':
            e = v['target']  # fresh coordinates from THIS turn's observation
            args = {'pid': self.pid, 'x': e['x'], 'y': e['y'], 'width': e['w'], 'height': e['h']}
            r = self.mcp.call('macos-use_click_and_traverse', args)
            call = {'tool': 'click_and_traverse', 'args': args, 'target_text': e['text'], 'target_id': v['target_id']}
        else:  # SCROLL
            args = {'pid': self.pid, 'x': 120, 'y': 450, 'deltaY': SCROLL_LINES[p['arg']]}
            r = self.mcp.call('macos-use_scroll_and_traverse', args)
            call = {'tool': 'scroll_and_traverse', 'args': args}
        call.update({'is_error': r['is_error'], 'summary': r['summary'][:600], 'app_switch': r['fields'].get('app_switch'),
                     'dialog': r['fields'].get('dialog'), 'shot': self.save_shot(r, 'after_action')})
        return call

    def run(self) -> dict:
        t0 = time.perf_counter()
        self.setup()
        history, stop, pending = [], None, None
        for i in range(MAX_PROPOSALS):
            if pending is not None:
                s, pending = pending, None
            else:
                s, _ = self.observe(f'step{i:02d}')
            if s.get('dialog'):
                stop = 'unexpected_dialog'
                break
            reached = self.reached(s)
            msgs = messages(self.goal, s, history, self.cond, FEWSHOT)
            gen = self.h.complete(msgs, FMT, MAX_NEW)
            p = parse_action(gen['raw'])
            v = validate(p, s)
            rec = {'i': i, 'observation': {k: s[k] for k in ('title', 'page', 'sidebar', 'buttons')} | {'closed': s.get('closed', False), 'shot': s.get('shot')},
                   'checker_reached_before_action': reached,
                   'model': {'prompt_user_turn': msgs[-1]['content'], 'prompt_tokens': gen['prompt_tokens'], 'output_tokens': gen['output_tokens'],
                             'total_tokens': gen['total_tokens'], 'seconds': gen['seconds'], 'raw': gen['raw'], 'hit_max_new': gen['hit_max_new']},
                   'parsed': {k: p.get(k) for k in ('format_ok', 'kind', 'arg', 'first_line')},
                   'harness': {'validation': v['status'], 'reason': v.get('reason')}, 'action_text': action_text(p, s)}
            self.steps.append(rec)
            if p.get('kind') == 'DONE' and p['format_ok']:
                stop = 'model_done'
                break
            if p.get('kind') == 'UNKNOWN' and p['format_ok']:
                stop = 'model_unknown'
                break
            if reached:
                rec['harness']['blocked'] = 'destination already reached; further actions are not executed'
                stop = 'missed_completion'
                break
            if v['status'] == 'out_of_scope':
                stop = 'out_of_scope'
                break
            if history and history[-1].get('no_change') and history[-1]['action_text'] == rec['action_text']:
                rec['harness']['blocked'] = 'repeat of an action that produced no change'
                stop = 'no_progress_loop'
                break
            if v['status'] != 'valid':
                rec['result_text'] = f'rejected ({v["reason"]}).'
                history.append({'action_text': rec['action_text'], 'result_text': rec['result_text'], 'no_change': True})
                pending = None  # re-observe: never reuse a previous turn's coordinates
                continue
            rec['execution'] = self.execute(p, v, s)
            if rec['execution']['app_switch'] or rec['execution']['dialog']:
                stop = 'unexpected_app_or_dialog'
                break
            s2, _ = self.observe(f'result{i:02d}')  # fresh observation after the action; becomes the next turn's state
            rec['result_text'] = describe_diff(s, s2)
            history.append({'action_text': rec['action_text'], 'result_text': rec['result_text'], 'no_change': state_key(s) == state_key(s2)})
            pending = s2
        else:
            stop = 'max_proposals'
        final, _ = self.observe('final')
        c = self.check()
        reached_final = c['running'] and any(norm(x) == norm(self.task['dest']) for x in c['selected'])
        result = {'task': self.task, 'condition': self.cond, 'goal': self.goal, 'stop': stop,
                  'checker_final': c, 'checker_reached_final': reached_final, 'final_window_title': final['title'],
                  'model_said_done': stop == 'model_done',
                  'fully_completed': stop == 'model_done' and reached_final,
                  'proposals': len(self.steps), 'executed': sum('execution' in r for r in self.steps),
                  'human_interventions': 0, 'seconds_total': time.perf_counter() - t0,
                  'identity': {'model_sha256': self.h.identity.get('model.safetensors'), 'runtime': 'models/hobbylm-1B-mlx/runtime (SHA256SUMS verified)',
                               'prompt_format': FMT, 'fewshot': FEWSHOT, 'prompt_sha256': self.prompt_sha,
                               'macos_use_commit': SERVER_COMMIT, 'server': self.mcp.server_info},
                  'steps': self.steps}
        self.mcp.close()
        return result


def prompt_fingerprint() -> str:
    src = (Path(__file__).parent / 'agent.py').read_bytes()
    return hashlib.sha256(src).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', required=True)
    ap.add_argument('--condition', choices=['A', 'B'], required=True)
    ap.add_argument('--set', default='held_out', choices=['dev', 'held_out'])
    a = ap.parse_args()
    tasks = json.loads((FROZEN / 'tasks.json').read_text())
    task = next(t for t in tasks[a.set] if t['id'] == a.task)
    sha = prompt_fingerprint()
    if a.set == 'held_out':
        frozen = json.loads((FROZEN / 'prompt.json').read_text())
        if frozen['agent_py_sha256'] != sha:
            raise SystemExit('agent.py changed after the prompt was frozen')
    if STOP.exists():
        raise SystemExit('STOP file present; remove it to run')
    out = WORK / 'runs' / f'{a.set}-{a.task}-{a.condition}-{time.strftime("%Y%m%d-%H%M%S")}'
    out.mkdir(parents=True)
    hobby = Hobby(check_weights=True)
    trial = Trial(task, a.condition, hobby, out, sha)
    try:
        res = trial.run()
    except KeyboardInterrupt as e:
        res = {'task': task, 'condition': a.condition, 'stop': f'interrupted: {e}', 'steps': trial.steps, 'human_interventions': 1}
        trial.mcp.close()
    (out / 'trial.json').write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str) + '\n')
    print(json.dumps({k: res.get(k) for k in ('stop', 'fully_completed', 'checker_final', 'proposals', 'executed', 'seconds_total')}, ensure_ascii=False), out)


if __name__ == '__main__':
    main()
