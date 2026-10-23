# Can unchanged HobbyLM-1B drive the Mac Calculator? (2026-10-20)

This test measured the base harness before any fine-tuning.

**The model and harness:** HobbyLM-1B Instruct MLX (`18382d78…`, macos-use `205c8880e8c0`).
HobbyLM proposes every action: `TYPE <keys>`, `CLEAR`, `DONE` or `UNKNOWN`. The harness:
- opens and clears Calculator, as setup
- shows HobbyLM the display
- allows only `0-9 . + - * / =`
- types through macos-use

A separate checker reads the display from the Accessibility API.

**The tasks:** 30 held-out requests and the pass bar were frozen before any model call
(`work/macos-agent/frozen/calc-tasks.json`). The prompt was frozen after 2 dev runs on 4 dev requests
(`calc-prompt.json`). The dev phase changed only the parse rule: the action is read from the start of the line, trailing text is
dropped and flagged, and keys are never edited.

## Result: fails the frozen bar overall; passes the "messy wording" bar

| | Simple (10) | Reversed order (8) | Messy wording (12) | **All (30)** |
|---|---|---|---|---|
| **Completed** (display = answer and model said DONE) | 8 | 3 | 6 | **17 (57%)** |
| Clean completion (one TYPE, Calculator did all the maths) | 6 | 2 | 4 | 12 (40%) |
| Regex baseline correct | 10 | 8 | 0 | 18 (60%) |
| Typed its own answer after `=` (e.g. `7*8=56`) | 3 | 1 | 3 | 7 |
| Said DONE on a wrong display | 0 | 2 | 4 | 6 |

**Frozen bar:**
- **Overall ≥ 80% completed:** **17/30 = 57% → FAIL.**
- **Messy wording ≥ regex + 20 points:** **6/12 = 50% vs 0% → PASS.**

**Other measures:**
- 70 proposals, all parseable. 51 were clean; 19 had trailing text dropped.
- 0 rejected, 0 out of scope, 0 human interventions.
- **Completion recognition:** it said DONE on 17 of the 19 trials where the display was right. It was also over-eager, saying
  DONE on 6 wrong displays.
- **Cost:** about 300 tokens per call (max 325, limit 1,024) and 0.66 s per model call. All 30 trials took 155 s.

## What it can and can't do

- **Strong on plain-English one-step maths that a regex can't parse:** "half of 18" → `18/2=`; "split 60 equally among 4 people" →
  `60/4=`; "three times four" → `3*4=`; "my bill is 450 and I pay 500" → `500-450=`.
- **Recognises finished results well:** DONE on 17 of 19 correct displays. The System Settings test got 0/4.
- **Gets operand order wrong:** "take 15 away from 40" → `15-40=`, and "what is 6 less than 20" → `6-2=`. The regex got all 8
  reversed-order requests right; HobbyLM got 3.
- **Drops or invents numbers:** "a dozen plus 5" → `5+5=`, "two hundred minus fifty" → `50-2=`, "3 pens at 12 each" → `3+12=`.
- **Does the maths itself:** 7 times it appended its own answer after `=`, and once that answer was wrong (`100-37=33`).

## Honest take

On simple and reversed wording, a 20-line regex beats it (18/18 vs 11/18). On messy wording it's genuinely useful (6/12 vs
0/12), but it's wrong often enough that every result needs checking. A reasonable product shape: a regex handles clear
phrasings, and HobbyLM is tried only when the regex can't parse, with the keys shown before Calculator runs them. Note that this
"before training" result is a baseline for the Codex calculator fine-tune handoff (`docs/CODEX_TOOL_CALL_FINETUNE_HANDOFF_2026-10-19.md`).

**Files:**
- `backend/capability/macos_agent/calc_run.py`, `calc_regex.py`, `calc_checker.swift`
- Per-step prompts, raw outputs and displays: `work/macos-agent/runs/calc-held_out-*/results.json`
- Scores: `work/macos-agent/calc-score.json`
