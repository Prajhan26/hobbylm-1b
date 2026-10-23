"""Offline checks on the 10-action harness (hobbymac_run.parse / validate). No model, no screen actions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from hobbymac_run import parse, validate  # noqa: E402

cases = [  # (raw model output, Calculator open?, expected status, expected kind, expected arg)
    (' OPEN Calculator', False, 'valid', 'OPEN', 'Calculator'),
    ('OPEN Calculator', True, 'invalid_state', 'OPEN', 'Calculator'),   # already open
    ('OPEN Notes', False, 'valid', 'OPEN', 'Notes'),
    ('OPEN Safari', False, 'out_of_scope', 'OPEN', 'Safari'),           # not on the app list
    (' TYPE 600/4=', True, 'valid', 'TYPE', '600/4='),
    ('TYPE 600/4=', False, 'invalid_state', 'TYPE', '600/4='),          # Calculator not open
    ('TYPE 14 x 9=', True, 'valid', 'TYPE', '14*9='),                   # x, ×, ÷, − are spelled as Calculator keys
    ('TYPE 12÷4=', True, 'valid', 'TYPE', '12/4='),
    ('KEY BRIGHTNESS_UP', False, 'valid', 'KEY', 'BRIGHTNESS_UP'),
    ('KEY mute', False, 'valid', 'KEY', 'MUTE'),
    ('KEY POWER', False, 'invalid_format', 'KEY', 'POWER'),             # not an allowed key
    ('DARK_MODE ON', False, 'valid', 'DARK_MODE', 'ON'),
    ('FOLDER Downloads', False, 'valid', 'FOLDER', 'Downloads'),
    ('FOLDER Pictures', False, 'out_of_scope', 'FOLDER', 'Pictures'),
    ('TIMER 10', False, 'valid', 'TIMER', '10'),
    ('TIMER 0', False, 'invalid_format', 'TIMER', '0'),
    ('TIMER 900', False, 'invalid_format', 'TIMER', '900'),             # over 10 hours
    ('SCREENSHOT', False, 'valid', 'SCREENSHOT', None),
    ('DONE', True, 'valid', 'DONE', None),
    ('UNKNOWN', False, 'valid', 'UNKNOWN', None),
    ('EVENT Call with dad | sunday | 19:00 | dad', False, 'valid', 'EVENT', 'Call with dad | sunday | 19:00 | dad'),
    ('rm -rf ~', False, 'invalid_format', None, None),                  # anything off the list is rejected
    ('Sure! OPEN Notes', False, 'invalid_format', None, None),
    ('open notes please', False, 'valid', 'OPEN', 'notes'),             # case-insensitive; trailing text is logged as not clean
    ('', False, 'invalid_format', None, None),
]

fails = 0
for raw, calc_open, want, kind, arg in cases:
    p = parse(raw)
    got = validate(p, calc_open)
    ok = got == want and p.get('kind') == kind and p.get('arg') == arg
    fails += not ok
    print(f'{"ok  " if ok else "FAIL"} {raw!r:52} -> {got} {p.get("kind")} {p.get("arg")!r}')

trailing = parse('OPEN Notes and then DONE')  # extra text after an action is recorded as not clean
print(f'{"ok  " if not trailing["clean"] else "FAIL"} trailing text marked not clean')
fails += trailing['clean']

print(f'ALL PASSED {len(cases) + 1}/{len(cases) + 1}' if not fails else f'{fails} FAILED')
sys.exit(1 if fails else 0)
