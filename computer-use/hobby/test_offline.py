"""Offline checks on saved System Settings observations: parsing, validation and rejection. No screen actions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from agent import closed_state, compact, parse_action, validate  # noqa: E402

O = Path(__file__).resolve().parents[1] / 'data' / 'observations'
mid = compact((O / 'dev-open-1.txt').read_text())
cases = [  # (raw model output, state, expected status, expected target text or None)
    ('OPEN System Settings', closed_state(), 'valid', None),
    (' OPEN system settings.', closed_state(), 'valid', None),
    ('OPEN Terminal', closed_state(), 'out_of_scope', None),
    ('OPEN Safari', mid, 'out_of_scope', None),
    ('OPEN System Settings', mid, 'invalid_state', None),
    ('CLICK Sound', closed_state(), 'invalid_state', None),
    (' CLICK Sound\nUSER: Goal: ...', mid, 'valid', 'Sound'),
    ('CLICK s11', mid, 'valid', 'Sound'),
    ('CLICK "Wallpaper"', mid, 'valid', 'Wallpaper'),
    ('CLICK Keyboard', mid, 'invalid_target', None),          # not visible in this observation
    ('CLICK Sounds', mid, 'invalid_target', None),            # no fuzzy matching
    ('CLICK s99', mid, 'invalid_target', None),               # invented id
    ('CLICK App 1', mid, 'invalid_target', None),           # content-area text is never clickable
    ('CLICK Back', mid, 'valid', 'Back'),
    ('SCROLL DOWN', mid, 'valid', None),
    ('SCROLL DOWN', closed_state(), 'invalid_state', None),
    ('DONE', mid, 'valid', None),
    ('UNKNOWN', mid, 'valid', None),
    ('Select the Sound option.', mid, 'invalid_format', None),
    ('type wallpaper into search', mid, 'invalid_format', None),
    ('', mid, 'invalid_format', None),
]
fails = 0
for raw, s, want, tgt in cases:
    v = validate(parse_action(raw), s)
    got_t = v.get('target', {}).get('text') if v.get('target') else None
    ok = v['status'] == want and (tgt is None or got_t == tgt)
    fails += not ok
    print('ok  ' if ok else 'FAIL', repr(raw[:30]), '->', v['status'], got_t or '')
assert all(k[0] == 's' or k[0] == 'b' for k in mid['targets'])
assert not any(e['role'] == 'AXCheckBox' for e in mid['targets'].values()), 'a content switch got an id'
print('content switches never clickable: ok')
print('FAILED' if fails else 'ALL PASSED', f'{len(cases) - fails}/{len(cases)}')
sys.exit(1 if fails else 0)
