"""Hobby: interactive offline Mac helper for demos (HobbyLM-1B Instruct + round-1 LoRA, everything local).

  TOKENIZERS_PARALLELISM=false .venv-mlx-release/bin/python backend/capability/macos_agent/hobby_demo.py
Type a request, press Enter. Hobby (the model) picks every action; this program only executes allowed actions and
shows each decision. Effects are REAL here (unlike the test runner): brightness/volume/dark mode stay changed, timers
fire a notification, screenshots go to the Desktop. Ctrl-C or Esc (during an action) to stop.
"""
import os
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import hobbymac_run as R  # noqa: E402  (same parse/validate/checkers as the tests)
from hobbymac_data import SYSTEM, SYSTEM_V2, state_text, user_turn  # noqa: E402
import calendar_tool as CAL  # noqa: E402
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
LOCAL_TZ = CAL.system_tz()  # the Mac's own time zone
DEMO_BRIGHTNESS_UP_TO_MAX = os.environ.get('HOBBY_DEMO_BRIGHT_MAX') == '1'  # demo only: 'brighter' jumps to 100% (tests and eval keep the normal ~6% key step)
EVENT_CALENDAR = os.environ.get('HOBBY_CALENDAR', 'Calendar')  # use an iCloud/Google calendar name to send invites
CALENDAR_ENABLED = os.environ.get('HOBBY_ENABLE_CALENDAR') == '1'  # opt-in: needs Calendar and Contacts access
PROMPT = SYSTEM
from mcp_client import MCP  # noqa: E402
from mlx_runtime import MlxHobby  # noqa: E402

W = R.WORK
G, Y, B, D, X = '\033[92m', '\033[93m', '\033[94m', '\033[2m', '\033[0m'


def timer(minutes):
    def ring():
        time.sleep(minutes * 60)
        R.osa(f'display notification "Your {minutes}-minute timer is done" with title "Hobby" sound name "Glass"')
    threading.Thread(target=ring, daemon=True).start()


def event_flow(arg, req=''):
    """Calendar: plain code resolves date/time/email; nothing is added or sent without the user's yes."""
    arg, notes = CAL.harden(arg, req)  # code cross-checks the model's form against your sentence
    for n in notes:
        print(f'  {D}check: {n}{X}')
    now = datetime.now(ZoneInfo(LOCAL_TZ))
    plan = CAL.plan_event(arg, now, LOCAL_TZ)
    if plan is None or str(plan.problem or '').startswith('could not'):
        print(f'  {Y}I could not understand the date or time.{X}'); return None
    if plan.problem:  # no email / several matches in Contacts
        print(f'  {Y}{plan.problem}{X}')
        e = input(f'  {G}email to invite (Enter = no invite) ›{X} ').strip()
        if e and CAL.EMAIL.match(e):
            plan.email, plan.email_source = e.lower(), 'typed'
        plan.problem = None
    for w in CAL.warnings(plan, CAL.parse_event(arg)[1], now):
        print(f'  {Y}note: {w}{X}')
    print(f'  {B}Add {CAL.describe(plan, LOCAL_TZ)}?{X}')
    if input(f'  {G}y / n ›{X} ').strip().lower() not in ('y', 'yes'):
        return None
    ok, out = CAL.create_event(plan, EVENT_CALENDAR, LOCAL_TZ, with_invite=bool(plan.email))
    if not ok:
        print(f'  {Y}Calendar refused: {out[:120]}{X}'); return None
    return 'event added to the calendar.'


def run(h, mcp, req):
    last, pid = None, None
    for i in range(6):
        co = R.running('Calculator') and bool(R.display())  # running without a window counts as not open
        b, (v, m) = R.bright(), R.vol()
        state = state_text(co, R.display() if co else None, round(b * 100), v, m, R.front(), R.dark())
        g = h.complete(PROMPT, user_turn(req, state, last))
        p = R.parse(g['raw'])
        status = R.validate(p, co)
        act = ' '.join(x for x in (p.get('kind'), p.get('arg')) if x) if p['format_ok'] else g['raw'].strip()[:40]
        print(f'  {D}{g["seconds"]:.1f}s{X}  Hobby → {B}{act}{X}', flush=True)
        if p['format_ok'] and p['kind'] == 'DONE':
            print(f'  {G}✓ done{X}\n'); return
        if p['format_ok'] and p['kind'] == 'UNKNOWN':
            print(f"  {Y}I can't do that one offline.{X}\n"); return
        if status != 'valid':
            print(f'  {Y}(not allowed — skipped){X}'); last = (act, 'rejected (not allowed in this state).'); continue
        k, a = p['kind'], p.get('arg')
        if k == 'OPEN' and a.lower() == 'calculator':
            R.sh('open', '-a', 'Calculator')  # 'reopen' brings back a window if Calculator runs windowless
            time.sleep(.6)
            pid = int(mcp.call('macos-use_open_application_and_traverse', {'identifier': 'Calculator'})['fields']['pid'])
            mcp.call('macos-use_press_key_and_traverse', {'pid': pid, 'keyName': 'Escape'})
            res = 'Calculator opened.'
        elif k == 'OPEN':
            R.sh('open', '-a', R.APPS[a.lower()]); time.sleep(1.2); res = f'{R.APPS[a.lower()]} opened.'
        elif k == 'TYPE':
            pid = pid or int(R.sh('pgrep', '-x', 'Calculator').split()[0])
            for _ in range(3):
                if R.front() == 'Calculator':
                    break
                mcp.call('macos-use_open_application_and_traverse', {'identifier': 'Calculator'})
            time.sleep(.4)
            before = R.display(); mcp.call('macos-use_type_and_traverse', {'pid': pid, 'text': a}); after = R.display()
            res = f'display changed from {before} to {after}.'
        elif k == 'KEY':
            if a.startswith('BRIGHTNESS'):
                bb = R.bright()
                if a.endswith('UP') and DEMO_BRIGHTNESS_UP_TO_MAX:  # demo setting: model still only chose BRIGHTNESS_UP
                    R.sh(str(W / 'brightness'), 'set', '1.0')
                else:
                    R.sh(str(W / 'brightness'), 'down' if a.endswith('DOWN') else 'up')
                ba = R.bright()
                res = f'brightness changed from {round(bb * 100)}% to {round(ba * 100)}%.'
            elif a == 'MUTE':
                R.osa('set volume output muted true'); res = 'sound muted.'
            else:
                vb = R.vol()[0]; R.sh(str(W / 'media_key'), a.lower()); time.sleep(.3); res = f'volume changed from {vb}% to {R.vol()[0]}%.'
        elif k == 'DARK_MODE':
            R.osa(f'tell application "System Events" to tell appearance preferences to set dark mode to {"true" if a == "ON" else "false"}')
            res = f'dark mode turned {a.lower()}.'
        elif k == 'FOLDER':
            R.sh('open', str(Path.home() / R.FOLDERS[a.lower()])); res = f'Finder opened the {R.FOLDERS[a.lower()]} folder.'
        elif k == 'EVENT' and not CALENDAR_ENABLED:
            print(f'  {Y}Calendar events are off by default. Set HOBBY_ENABLE_CALENDAR=1 to turn them on.{X}\n'); return
        elif k == 'EVENT':
            res = event_flow(a, req)
            if res is None:
                print(f'  {Y}cancelled — nothing was added.{X}\n'); return
        elif k == 'TIMER':
            timer(int(a)); res = f'timer set for {int(a)} minutes.'
        else:  # SCREENSHOT
            f = Path.home() / 'Desktop' / f'Hobby screenshot {time.strftime("%H.%M.%S")}.png'
            R.sh('screencapture', '-x', str(f)); res = 'screenshot saved to the Desktop.'
        print(f'  {G}↳ {res}{X}', flush=True)  # visible proof in screen recordings (brightness/volume aren't visible as pixels)
        last = (act, res)
    print(f'  {Y}(stopped after 6 steps){X}\n')


def main():
    global PROMPT
    rnd = sys.argv[1] if len(sys.argv) > 1 else 'r1'   # r3 adds the calendar skill
    PROMPT = SYSTEM_V2 if rnd in ('r3', 'r4') else SYSTEM
    print(f'{D}Loading HobbyLM-1B + Hobby adapter ({rnd}) from this Mac (MLX)…{X}', flush=True)
    h = MlxHobby(W / f'hobbymac-lora-{rnd}-ab.npz')  # r1 decisions verified identical to the PyTorch run (203/203)
    h.complete(SYSTEM, user_turn('warm up', state_text(False, None, 50, 50, False), None), max_new=2)
    mcp = MCP()
    if R.osa('tell application "System Events" to get UI elements enabled') != 'true':  # Accessibility check (silent failures otherwise)
        print(f'{Y}⚠ Accessibility permission is OFF for the app running Hobby, so Calculator typing and screen reading will fail.\n'
              f'  Turn it on: System Settings → Privacy & Security → Accessibility → enable your terminal app, then restart it.{X}')
    print(f'{G}Hobby is ready — running fully on this Mac.{X}\n')
    try:
        while True:
            req = input(f'{G}you ›{X} ').strip()
            if req:
                run(h, mcp, req)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        mcp.close()


if __name__ == '__main__':
    main()
