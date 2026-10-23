# Hobby demo: final script (~45 s, one story, no title cards)

**The story:** Mom asks what HobbyLM can do → Wi‑Fi goes off → Hobby shows it → Wi‑Fi back on → Mom replies.
**Lines:** every typed line was rehearsed live with the round-4 adapter and worked first time.

## Before recording
1. **Mac state:**
   - Do Not Disturb on
   - Dock hidden
   - light mode
   - brightness about 70% (set by hand; one Hobby step is about 6%)
   - Calculator and Notes quit
   - a clean Desktop
2. **Terminal on the right**, with a big font. Start Hobby **while Wi‑Fi is still on** (it loads from disk; it doesn't need Wi‑Fi):
   `cd ~/refuel/HobbyLM && TOKENIZERS_PARALLELISM=false .venv-mlx-release/bin/python backend/capability/macos_agent/hobby_demo.py r4`
   Do one warm-up line, then ⌘K to clear.
3. **Export the two notification clips** from `HobbyLM_Notification_Intro.html`, using a desktop screenshot that has this Terminal on
   screen:
   - **Intro:** Mom: "What can your 1B HobbyLM do? Dad is concerned." → reply "Show him this video" ✓✓
   - **Outro:** Mom: "Dad says ok 👍" (no reply)

## The recording (one Openscreen take)

| # | ~Time in final cut | You do / type | Viewers see |
|---|---|---|---|
| 1 | 0–8s | *(the intro clip goes here in CapCut)* | Mom's message, your reply ✓✓ |
| 2 | 8–11s | click the Wi‑Fi icon → **turn Wi‑Fi off** | the crossed-out Wi‑Fi icon |
| 3 | 11–18s | `split 600 among 4 people` | Calculator opens, types `600/4=` → **150** |
| 4 | 18–22s | `dim my screen` | Terminal prints **↳ brightness changed from 70% to 64%** (a screen recording can't show the backlight itself) |
| 5 | 22–27s | `I need to write something down` | Notes opens |
| 6 | 27–30s | `grab a screenshot` | the screenshot appears on the Desktop |
| 7 | 30–34s | `what's the weather tomorrow` | *"I can't do that one offline."* |
| 8 | 34–38s | `turn on dark mode` (last, so the video stays bright) | the whole Mac turns dark |
| 9 | 38–41s | click Wi‑Fi → **turn Wi‑Fi on** | Wi‑Fi reconnects |
| 10 | 41–45s | *(the outro clip goes here)* | Mom: **"Dad says ok 👍"** |
| 11 | 45–48s | end card | **HobbyLM-1B · fine-tuned 11 min · offline on a MacBook Air · 72% of 125 sealed requests** |

**Small captions are optional** (no cards), in the same corner each time:
- step 2: "no internet"
- step 3: "Calculator does the maths"
- step 7: "it knows what it can't do"

## Tips
- **Hold each result about 1 second** before typing the next line (150 on Calculator, the dimmed screen, Notes open, dark mode,
  the screenshot file).
- **Keep every `Hobby →` line visible.** Cut only the waiting, and label any speed-up.
- **If a line fails, retype it** in the same take and cut the miss. Never splice in a fake result.
- **Backups (also rehearsed OK):** `dinner bill 2400 split among 4 of us`, `mute everything`, `screenshot please`.
- **Say "grab a screenshot",** not "take a screenshot".
- **CapCut order:** intro → recording (steps 2–9) → outro → end card. Add a notification ding on both messages, soft music, and
  a zoom on Calculator at step 3.
