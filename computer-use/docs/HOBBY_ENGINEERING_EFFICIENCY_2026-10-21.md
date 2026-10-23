# Hobby: how we made a 1B model run a Mac efficiently (2026-10-21)

**What Hobby is:** HobbyLM-1B Instruct plus a small trained add-on (LoRA). It turns a plain-English request into one Mac action and
says when it's done. It runs offline on a MacBook Air. Training used a cloud H100 for 11–24 minutes per round.

**Headline numbers:**

| | Before | Now |
|---|---|---|
| Time per decision | 3.4 s | **~0.25 s** (up to ~0.7 s for calendar answers) |
| Reading the prompt (prefill) | ~196 tok/s | **~1,625 tok/s** |
| Writing the answer (decode) | ~1 tok/s | **~46 tok/s** |
| Tokens per call (budget 1,024) | ~580 (with examples) | **~270–310** |
| Answers changed by the speed-up | — | **none** (233/233 decisions identical) |
| Sealed test, best adapter (round 3) | 0/107 untrained | **81/107 (76%)** |

All speed numbers were measured on a MacBook Air (Apple Silicon, built-in GPU), FP32, greedy decoding.

---

## 1. The overall design: let the model do only the part it's good at

```
you type ──► Hobby harness ──► HobbyLM (1 short decision) ──► harness checks it ──► plain code / macOS does the work ──► checker reads the real result
```

The biggest efficiency decision wasn't a speed trick. It was **giving the 1B model the smallest possible job**:

1. **The model never navigates screens step by step.** Every skill is **one structured action**: `OPEN Notes`, `TYPE 600/4=`, `KEY BRIGHTNESS_DOWN`,
   `EVENT Call with Naval | tuesday | 15:00 UTC | Naval`.
2. **The model never does the hard deterministic work.** Calculator computes the maths ("calculator orchestration"). Plain code
   turns "tuesday 3pm UTC" into an exact date and time, looks up emails in Contacts, and converts time zones.
3. **Short outputs:** most actions are 3–8 tokens, so writing time is tiny.
4. **Direct system calls instead of clicking through UI:**

   | Action | How it's done |
   |---|---|
   | Brightness | macOS DisplayServices (set and read) |
   | Volume and mute | hardware media-key events and `osascript` |
   | Apps and folders | `open -a` / `open <folder>` |
   | Screenshots | `screencapture` |
   | Dark mode | System Events appearance setting |
   | Calendar | AppleScript |

   These are instant and reliable. The accessibility server (`mcp-server-macos-use`) is used only where a real UI must be
   driven: opening Calculator and typing into it.

## 2. Inference engineering (making each decision fast)

| # | Technique | What it means | Effect |
|---|---|---|---|
| 1 | **KV cache** | Read the prompt once and keep the model's attention "notes", instead of re-reading the whole prompt before every new token | decode 1 → 2 tok/s (PyTorch) |
| 2 | **Apple MLX runtime** | Run on Apple's own ML framework, built for Apple Silicon's shared memory and GPU. PyTorch's Mac backend ("MPS") pushed some mixture-of-experts steps onto the CPU every token | prefill 196 → 1,625 tok/s; decode 2 → 46 tok/s |
| 3 | **Reuse the team's released MLX runtime** | No new engine written. We loaded the FP32 Instruct weights through `work/hobbylm-1B-mlx-release/runtime`, which already has a cache | zero new inference code to trust |
| 4 | **Pre-merge the LoRA at startup, in memory** | The add-on's correction (`weight += scale · B·A`) is added to the weights once when Hobby starts, so each decision runs a plain model. No merged copy is written to disk (disk was nearly full) | no per-step adapter cost |
| 5 | **Keep FP32 (no quantisation)** | Compression (8-bit/4-bit) could be faster but can change answers. We chose identical behaviour | speed-up with **0 answer changes** |
| 6 | **Short, zero-shot prompt** | Before training, the prompt needed worked examples (~580 tokens). After training, the model knows the format, so the prompt is just the action list plus a 4-line state block (~270–310 tokens) | about half the reading per call |
| 7 | **Compact state, not the whole screen** | Hobby sees `Calculator: open, display shows 0 / Front app / Brightness / Volume / Dark mode`, not a 260-element accessibility tree | small prompts, fewer distractions |
| 8 | **Greedy decoding, stop at end-of-answer** | No sampling. Generation stops the moment the model ends its line | deterministic and short |
| 9 | **Output cap sized to the job** | 48 new tokens: enough for an EVENT line (~25–35), still tiny. (16 was too small and cut "Arjun" to "Ar") | no truncation, no waste |
| 10 | **Warm-up call at startup** | The first call on a Mac prepares GPU code, so we do it before the user types | the first real request is fast too |
| 11 | **Hard token budget** | Prompt plus answer must fit in 1,024 tokens. Code refuses rather than silently cutting the prompt | predictable cost; never exceeded (max seen 356) |

**How we proved the speed-up didn't change behaviour:**
- MLX vs PyTorch on all **203** decisions from the live round-2 test: **203/203 identical**.
- On 30 round-3 decisions: **30/30 identical**.
- Cached vs uncached PyTorch: **10/10 identical**.

## 3. Training engineering (cheap, fast, honest)

| Technique | What it means |
|---|---|
| **LoRA (rank 16)** | Train a small add-on (attention plus the dense MLP layer, 83 matrices) instead of the whole 1B model, so it fits easily on one GPU and trains in minutes |
| **Routers frozen** | The mixture-of-experts router and its balancing bias are not updated, so expert routing stays as released |
| **Loss on the action only** | The model is graded only on the answer tokens (`OPEN Notes` + end), not on re-predicting the prompt, so every step teaches the actual skill |
| **One-decision examples** | Each training example is one turn (state → next action), matching exactly how Hobby is used |
| **Synthetic templates** | 5,650–8,250 generated requests per round with the correct action, including word numbers, reversed order, Indian-English, near-misses to refuse, and calendar forms |
| **Leakage filter** | Any training example too similar to a test request (word overlap ≥ 0.5) is dropped (532–920 per round), so the test stays unseen |
| **Same weights verified on the GPU** | The H100 job checks the FP32 Instruct weight hash (`d0899e0a…`) before training |
| **Cost** | 10.7–23.8 H100-minutes per round, a few dollars each |

## 4. Harness and evaluation engineering (fast and trustworthy testing)

1. **The model decides; code only checks and executes.** Invalid actions are rejected. The only rewrites are spelling x, ×, ÷, − as Calculator keys and the calendar cross-checks, which are shown to the user before confirmation.
2. **Independent checkers read the real Mac state:** the Calculator display (Accessibility API), brightness (DisplayServices),
   volume and dark mode (`osascript`), the front app, Finder's window path, and calendar events read back.
3. **Everything is restored after each test trial:** brightness, volume, dark mode, opened apps and windows, screenshots and
   test events. Calendar tests use a separate "Hobby Test" calendar and never send invites.
4. **Sealed tests:** Grok writes them, they're fingerprinted before training, and the pass bars are written down first.
5. **Faster evaluation:** the test runner can use MLX (`--runtime mlx`). A 107-request live test takes about 15 minutes instead of
   about 20+, most of it now spent waiting for the Mac to act rather than for the model.
6. **Bugs we found and fixed in the harness**, each re-run only for the affected trials and documented:
   - keys typed before Calculator was ready
   - setup couldn't find bottom-of-list panes
   - a 16-token output cap
   - a path bug on Modal
   - a zsh word-splitting script bug

## 5. What's still slow or inefficient (next steps)

| Idea | Expected gain | Risk / check needed |
|---|---|---|
| **Cache the fixed system prompt once** (it's identical on every call; only the state block changes) | prefill per call drops from ~300 to ~60 tokens | verify identical outputs |
| **Use the released partial-8-bit MLX build** | faster and less memory | different weights; re-check the adapter's answers |
| **Store the LoRA as its small A/B matrices** instead of 540 MB pre-multiplied deltas | ~50× smaller files, faster startup | none if outputs match |
| **Keep the model loaded as a background service** | instant start, no ~1 min load | memory use while idle |
| **More training-data fixes** (timer hours, emails in events, reversed order) | accuracy, not speed | needs a fresh sealed test each round |

## 6. Files

| What | Where |
|---|---|
| MLX runtime (fast path) | `backend/capability/macos_agent/mlx_runtime.py` |
| PyTorch runtime (reference, with KV cache) | `backend/capability/macos_agent/torch_runtime.py` |
| Demo app | `backend/capability/macos_agent/hobby_demo.py` (start: `.venv-mlx-release/bin/python … hobby_demo.py r3`) |
| Test runner / scorer | `hobbymac_run.py` (`--runtime mlx`) / `hobbymac_score.py` |
| Training (Modal) and data | `hobbymac_modal.py`, `hobbymac_data.py` |
| Calendar skill | `calendar_tool.py` |
| Checkers and system tools | `calc_checker.swift`, `brightness.swift`, `media_key.swift` |
| Results and reports | `docs/HOBBYLM_MAC_HELPER_TRAINING_2026-10-20.md`, `work/macos-agent/runs/`, `work/macos-agent/mlx-parity-r2.json` |
