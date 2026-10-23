# Hobby Mac helper: before vs after a $-cheap fine-tune (2026-10-20)

**The question:** can a small LoRA fine-tune of HobbyLM-1B Instruct turn plain requests into the right Mac action, and know when
it's done?

**The actions:**
- Calculator
- brightness
- volume and mute
- dark mode
- open an app or a folder
- timer
- screenshot
- refusing requests it can't do

**The test:** 95 requests written by Grok, sealed (sha256 `22622047…`) before any training example was finalised. Training
examples resembling a test request (word-set Jaccard ≥ 0.5) were removed (788 of 5,650). The pass bar was frozen before
training, then amended once (before the test existed) to add the new skills.

**The setup:**
- **Base:** HobbyLM-1B Instruct FP32 (`d0899e0a…`).
- **Adapter:** LoRA r16 (`e505a773…`), trained on 4,712 synthetic one-step decisions in 11.2 H100-minutes.
- **Runs:** both models were run live on this Mac through the same harness. HobbyLM chose every action. The checkers read the real
  result from macOS: the Calculator display, the brightness value, the volume settings, the dark-mode setting, the front app,
  Finder's front window path, the recorded timer, and the screenshot file. Everything was restored after each trial.

## Results (live, 95 sealed requests)

| Skill | Untrained | **Trained** | Bar | |
|---|---|---|---|---|
| Calculator: clean completed (Calculator did the maths; regex baseline 6/30) | 0/30 | **22/30 (73%)** | 90% | fail |
| Brightness / volume / mute | 0/15 | **10/15 (67%)** | 85% | fail |
| Dark mode | 0/6 | **3/6** | 85% | fail |
| Open an app | 0/10 | **9/10 (90%)** | 85% | **PASS** |
| Open a folder | 0/6 | **3/6** | 85% | fail |
| Timer | 0/8 | **5/8** | 85% | fail |
| Screenshot | 0/4 | **2/4** | 85% | fail |
| Refuse what it can't do | 0/16 | **7/16 (44%)** | 80% | fail |
| **All** | **0/95** | **61/95 (64%)** | every row | **fail (1 of 8 skills passes)** |

**How the replies changed:**

| | Untrained | Trained |
|---|---|---|
| Readable actions | 42 of 224 | 206 of 206 |
| Rejected | 212 | 4 |
| Model time per call | 6.8 s | 3.4 s |

Both used about 270–280 tokens per call (limit 1,024).

**Note on the untrained number:** it's zero-shot with this prompt. With 3 worked examples in the prompt, the untrained model scored
57% on the earlier, easier Calculator set. So "0/95" mostly means "can't follow this format cold".

## Why it failed, by type (all from the trial logs)

1. **Word numbers without hyphens:**
   - "forty plus sixty six" → `46+66=`
   - "nine hundred divided by thirty" → `9100/30=`
   - "one fifty minus eighty eight" → `1*88=`

   Training only wrote hyphenated forms ("sixty-six") and never the Indian "one fifty".
2. **Reversed order:** "take 13 off 50" → `13-50=`, "how much less is 27 than 90" → `27-90=`. To keep training away from the
   Grok prompt's own examples, I renamed the "take X off Y" templates. That removed exactly the coverage this needed.
3. **Hours:** "in an hour" → `TIMER 30`, "1.5 hours" → `TIMER 1`, "2 hrs" → `TIMER 2`. Training had few hour phrasings, and
   none with digits.
4. **Meaning, not keywords:**
   - "screen is too bright" → `BRIGHTNESS_UP`
   - "my eyes hurt at night, make everything dark" → `BRIGHTNESS_UP`
   - "switch to the black theme" → `DARK_MODE OFF`
5. **Folders and apps it confused:** "open desktop folder" → `OPEN Documents`; "open apple music" → `OPEN Apple`.
6. **Over-eager on near-misses (9 of 16):**
   - "play loud music on Spotify" → `VOLUME_UP`
   - "what does dark matter mean" → `BRIGHTNESS_DOWN`
   - "average of 40, 55 and 70" → typed `40+55+70=`
   - "delete the screenshots" → took a screenshot

   Training had generic refusals but almost no tricky near-misses.

## What this means

- **Fine-tuning works:** 0 → 61 of 95 for 11 GPU-minutes. Every reply became a valid action, and it learned to say DONE.
- **It isn't demo-ready on the frozen bar.** Only "open an app" passes. The failures come from **gaps in my training templates**
  (word-number forms, hours, reversed phrasing, near-misses), not from a hard model limit.
- **This test set is now used up for claims.** I've read its failures, so a v2 training set would be tuned to them. The next honest
  step: fix the template gaps, get a **fresh** sealed Grok set, and retrain (another ~11 GPU-minutes).

**Files:**
- Training script: `backend/capability/macos_agent/hobbymac_modal.py`; data: `hobbymac_data.py`; runner: `hobbymac_run.py`;
  scorer: `hobbymac_score.py`
- Frozen inputs: `work/macos-agent/frozen/hobbymac-*`
- Training result: `work/macos-agent/hobbymac-train-results.json`
- Live runs, with every step, raw output and checker value: `work/macos-agent/runs/hobbymac-sealed-{untrained,trained}-*/`

## Round 2 (fresh sealed Grok test `9c28e19c…`, 95 requests)

**What changed in round 2:**
- **Training data** was rebuilt after reading the round-1 failures, adding: number words (unhyphenated, "one fifty"), reversed-order
  phrasings, hours, meaning-based brightness and dark-mode wording, app vs folder contrasts, and about 660 near-miss refusals.
  That gave 7,350 generated examples; 920 that resembled the new test were dropped, leaving 6,280 to train on.
- **Adapter:** `8159d4c7…`, trained in 10.7 H100-minutes.
- **Owner's second bar:** recorded mid-run (`hobbymac-pass-bar-amendment-2-owner-75.json`), before any round-2-adapter result
  was read, but after the round-1 adapter had been scored on this test.

**Harness bug found and fixed:** in 2 trials (C02, C18), keys typed right after Calculator launched were dropped
(`518-247=` arrived as `58-247=`). HobbyLM's keys were correct. The runner now waits for Calculator to be frontmost before typing,
and those 2 trials were re-run. No other run had this problem (checked: 0 cases in every other run).

**Results:**

| Skill | Round-1 adapter | Round-2 adapter (after the fix) | Frozen bar | Owner bar 75% |
|---|---|---|---|---|
| Calculator: clean (regex 5/30) | 23/30 (77%) | 23/30 (77%) | 90% ❌ | ✅ both |
| Brightness / volume / mute | 10/15 (67%) | 11/15 (73%) | 85% ❌ | ❌ both |
| Dark mode | 2/6 | 3/6 | ❌ | ❌ |
| Open an app | **10/10** | 7/10 | r1 ✅ | r1 ✅, r2 ❌ |
| Open a folder | 4/6 | **5/6 (83%)** | ❌ | r2 ✅ |
| Timer | 5/8 | 5/8 | ❌ | ❌ |
| Screenshot | **4/4** | 1/4 | r1 ✅ | r1 ✅, r2 ❌ |
| Refuse what it can't do | 13/16 (81%) | **14/16 (88%)** | ✅ both | ✅ both |
| **All** | **71/95** | **70/95** | | |

**What round 2 taught us:**
- **The extra near-miss refusals made the model over-cautious.** It answered UNKNOWN to "open finder window", "open music, need to
  focus", "save a picture of my screen" and "volume badhao".
- **Still failing:**
  - number words: "hundred minus thirty seven" → `127-37`, "two dozen times five" → `2*5`
  - reversed order: "how much less is 27 than 80" → `27-80`
  - hour arithmetic: "1 hr 15 min" → `TIMER 135`, "quarter of an hour" → `TIMER 60`
- **Neither adapter is ready for a demo across all skills.** Picking the better adapter for each skill would be cherry-picking, so we
  don't report it.

## Round 3 (2026-10-21): calendar events added; fresh sealed Grok test `02f7b693…` (107 requests)

**Setup:**
- **Training changes:**
  - calendar `EVENT <title> | <day> | <time> [tz] | <person or email>` with 1,200 examples
  - near-miss refusals cut from 60% to 30%
  - more "1 hr 15 min" and "two dozen" forms
- **Training size:** 7,568 examples after 532 test lookalikes were dropped.
- **Adapter:** `c572c909…`, trained in 23.8 H100-minutes.
- **Runtime:** runs on MLX (30/30 decisions identical to PyTorch).
- **Calendar tests:** used a separate "Hobby Test" calendar, never sent invites, never read real Contacts, and were deleted afterwards
  (0 events left).
- **Harness fix:** the output limit was 16 tokens, which cut off 2 EVENT answers (`| Ar…` for Arjun). It was raised to 48, and only
  the 12 calendar requests were re-run. Other skills' answers are short and were unaffected.

**Results on the same round-3 test:**

| Skill | Round-1 adapter | **Round-3 adapter** | Frozen bar | Owner bar 75% |
|---|---|---|---|---|
| Calculator: clean (regex 4/30) | 23/30 | **25/30 (83%)** | 90% ❌ | ✅ |
| Brightness / volume / mute | 13/15 | 11/15 (73%) | ❌ | ❌ |
| Dark mode | 2/6 | **5/6** | ❌ | ✅ |
| Open an app | 9/10 | **10/10** | ✅ | ✅ |
| Open a folder | 4/6 | 4/6 | ❌ | ❌ |
| Timer | 4/8 | 4/8 | ❌ | ❌ |
| Screenshot | 4/4 | 4/4 | ✅ | ✅ |
| Refuse what it can't do | 8/16 | **13/16 (81%)** | ✅ | ✅ |
| Calendar event (new) | 0/12 (never trained) | **5/12** (4/11 without E01, the prompt's own example) | ❌ | ❌ |
| **Non-calendar total** | 67/95 | **76/95 (80%)** | | |
| **All 107** | 67/107 | **81/107 (76%)** | | |

**What the remaining failures show:**
- **Calendar:**
  - It replaces an email with a name ("sync with ananya@example.com" → `| Ananya`). That comes from my training titles, which used
    the name.
  - It confuses "3 nov 10 am" → `nov 10 | 03:00`.
  - It drops the day ("demo … today 6:15pm" → day missing).
  - It refuses "lock in a chat w/ Riya fri 5pm" and "put gym session tomorrow 7 am".
- **Timer hours:** "timer of 4 hours" → `TIMER 4`, "2 hr" → `TIMER 2`. It still writes hours, not minutes.
- **Reversed order and number words:** these persist ("how much smaller is 48 than 91" → `48-91`; "nine hundred minus three
  twenty" → `9100-323`).
- **Meaning:** "screen is blinding me in bed" → brightness **up**.

## Round 4 (2026-10-21): calendar-focused fixes; fresh sealed Grok test `f1a33389…` (125 requests, 30 events)

**Setup:**
- **Training changes:** emails kept as written, "3 nov 10 am"-style dates, casual event phrasing, and hours → minutes. That gave
  1,800 event examples, and 7,909 training examples after dropping 791 test lookalikes.
- **Adapter:** `175bbb49…`, trained in 14.3 H100-minutes.
- **Runtime:** MLX, compact 14 MB adapter files (203/203 identical decisions to PyTorch).

**Results on the same round-4 test:**

| Skill | Round-3 adapter | **Round-4 adapter** |
|---|---|---|
| Calculator: clean (regex 5/30) | 22/30 | 20/30 |
| Brightness / volume / mute | 11/15 | 11/15 |
| Dark mode | 4/6 | 4/6 |
| Open an app | 8/10 | 8/10 |
| Open a folder | 5/6 | 5/6 |
| Timer | 6/8 | 5/8 |
| Screenshot | 2/4 | 2/4 |
| Refuse | 13/16 | 14/16 |
| **Calendar event** | 14/30 | **21/30 (70%)** |
| **All 125** | 85 (68%) | **90 (72%)** |

**Demo-line rehearsal (11 lines, live):** round-3 adapter **11/11**; round-4 adapter 9/11. Round 4 answered UNKNOWN to
"take a screenshot", and the "write something down" trial failed its check after opening Notes.

**Takeaways:**
- **Calendar improved substantially:** +7 of 30.
- **Other skills held or dipped slightly.** Calculator and timer each lost 1–2, which is within noise on these set sizes.
- **Remaining calendar errors:**
  - am/pm slips ("4:45pm" → 04:45, "8am" → 20:00)
  - emails dropped or shortened (`hari@fuellabs`)
  - the title or day field occasionally swapped with the email

## Calendar safety checks (2026-10-22, harness only, no retraining)

**What changed:** after HobbyLM writes the EVENT form, plain code (`calendar_tool.harden` + `warnings`) cross-checks it against the
user's own sentence:
- emails are copied exactly
- an explicit am/pm or hh:mm time wins
- a missing day is taken from the sentence
- extra fields are dropped
- only people named in the sentence are invited
- it uses the Mac's own time zone
- it warns about past times, "Tuesday" said on a Tuesday, and "next Friday" ambiguity

Every correction is shown to the user as `check: …` before the y/n confirmation. The Contacts lookup no longer crashes when Contacts
isn't running (it falls back to asking for the email).

**Effect on the 30 round-4 calendar requests** (same logged model outputs): **model alone 21/30 → model + checks 27/30**, with
**0** correct answers broken. The remaining 3 have the right date, time and invitee, but a shorter title than expected.
**Caveat:** the checks were written after seeing these 30 requests. A fresh sealed calendar test is needed before claiming 27/30.

**Still open:**
- a real invite test (the user sends one to their own email; if none arrives, the "Calendar" calendar is local-only and Hobby must
  target an iCloud or Google calendar)
- event length is fixed at 30 minutes
- you can't choose which calendar
- no editing or cancelling events
