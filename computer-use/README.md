# Hobby: on-device computer use with HobbyLM-1B

![HobbyLM-1B Computer Use: plain English in, one Mac action out](assets/hero.png)

Hobby turns plain-English requests into actions on a Mac, one step at a time, running entirely on the device. The decisions come
from [**HobbyLM-1B Computer Use**](https://huggingface.co/Hobbylm/hobbylm-1B-computer-use), a LoRA adapter for HobbyLM-1B Instruct.
This repository holds the app, the harness, the evaluation suite and the training pipeline.

- **90 of 125** sealed requests completed live on macOS (72%). The pre-registered pass bars were not met; see [Results](#results).
- **0.26 s** median per decision on a MacBook Air (Apple MLX, FP32, round-4 adapter, model time)
- **9 skills:** Calculator, brightness, volume, dark mode, apps, folders, timers, screenshots, calendar events, plus knowing when
  to say no
- **14 MB** adapter, trained in 4 rounds on 60 H100-minutes

## Quickstart

**Requirements:** an Apple-silicon Mac, macOS 14 or later, Python 3.10 to 3.13 and the Xcode command-line tools.

```bash
git clone https://github.com/fuellabs-ai/hobbylm-1b && cd hobbylm-1b/computer-use
./scripts/setup.sh
.venv/bin/python hobby/hobby_demo.py r4
```

`setup.sh` installs pinned packages and downloads HobbyLM-1B Instruct, the MLX runtime and the adapter. It also builds
[`mcp-server-macos-use`](https://github.com/mediar-ai/mcp-server-macos-use) at a pinned commit and compiles the Swift helpers.
Hobby runs offline from then on.

```text
you › split 600 among 4 people
  0.3s  Hobby → OPEN Calculator
  ↳ Calculator opened.
  0.3s  Hobby → TYPE 600/4=
  ↳ display changed from 0 to 150.
  0.2s  Hobby → DONE
  ✓ done
```

### Hobby bar (⇧⌘H)

`setup.sh` also builds **Hobby bar**, a Spotlight-style search field. Start it once:

```bash
data/HobbyBar
```

**Using it:**
- A `hobby` item appears in the menu bar.
- Press **⇧⌘H** anywhere, type a request and press Enter. Each decision appears under the field as it happens.
- Calendar questions such as `y / n` are answered in the same field.
- **Esc** hides the bar.

**How it behaves:**
- The model stays loaded in the background, so requests start immediately.
- The bar never takes focus from the app you're in, so the model sees the Mac as you left it.
- Hotkey: ⇧⌘H is the default (`cmd-shift-h`). Set `HOBBY_BAR_HOTKEY` to `ctrl-option-space`, `option-space` or `cmd-shift-space` for another chord. Optional `cmd-h` uses ⌘H and replaces the system Hide shortcut while Hobby runs.

**Permissions.** You grant these in System Settings; Hobby never grants anything itself.

- **Accessibility:** for the app that runs Hobby. Hobby checks this at startup.
- **Calendar and Contacts:** for calendar events only. Turn the skill on with `HOBBY_ENABLE_CALENDAR=1`, and pick a calendar with
  `HOBBY_CALENDAR="<calendar name>"`.

Press Ctrl-C to quit, or Esc to stop a UI action.

## Skills

| Skill | Example request | Action |
|---|---|---|
| Calculator | `split 600 among 4 people` | `OPEN Calculator` → `TYPE 600/4=` → `DONE` |
| Brightness | `screen faded, more light needed` | `KEY BRIGHTNESS_UP` |
| Volume | `sound is harsh, turn it down a notch` | `KEY VOLUME_DOWN` |
| Mute | `mute everything` | `KEY MUTE` |
| Dark mode | `flip to dark theme, late night work` | `DARK_MODE ON` |
| Open an app | `gotta scribble a quick note` | `OPEN Notes` |
| Open a folder | `need papers from documents` | `FOLDER Documents` |
| Timer | `remind me after 4 hours to stretch` | `TIMER 240` |
| Screenshot | `snap my screen` | `SCREENSHOT` |
| Calendar event | `coffee with Meera wednesday 10am` | `EVENT Coffee with Meera \| wednesday \| 10:00 \| Meera`, then a y/n confirmation |
| Out of scope | `will it rain in mumbai tonight` | `UNKNOWN` |

## How it works

![How one step works](assets/how-it-works.png)

1. **The model writes one action.** Hobby sends the request and the live Mac state to the model, which writes one action from a
   fixed vocabulary of ten.
2. **The harness validates and executes it.** It checks the action against an allow-list and executes it: Calculator through
   `mcp-server-macos-use`, everything else through direct macOS calls.
3. **The result goes back to the model.** The model writes the next action until it writes `DONE`, with at most 6 steps.
4. **Calendar events are checked and confirmed.** Plain code resolves the date, time and time zone, copies emails exactly from
   the sentence and looks up Contacts. Any change to the model's fields is shown, and Hobby always asks **y/n** before adding
   anything. If the event has an email address, confirming it sends a real invitation.

Invalid actions are rejected. The harness spells `x`, `×`, `÷` and `−` as Calculator keys.

## Results

![Round-4 sealed live test results](assets/results.png)

**How the tests were run:**

- A separate model wrote each round's tests, which were sealed (sha256) before training.
- Training lookalikes were removed by word-set Jaccard similarity.
- Every trial ran live on a MacBook Air, with independent checkers reading the result from macOS.

**Pass bars.** Neither pre-registered pass bar was met in round 4:

- **The frozen bar:** every skill had to clear it (Calculator ≥ 90%, refusals ≥ 80%, every other skill ≥ 85%). Only refusals did.
- **The owner's 75% bar:** apps, folders and refusals cleared it.

The score file records both results (`all_pass: false`, `all_pass_owner_75: false`).

Full details are on the [model card](https://huggingface.co/Hobbylm/hobbylm-1B-computer-use) and in
[`docs/HOBBYLM_MAC_HELPER_TRAINING_2026-10-20.md`](docs/HOBBYLM_MAC_HELPER_TRAINING_2026-10-20.md).

![Per-decision latency](assets/speed.png)

## Reproduce

| Task | Command |
|---|---|
| Live sealed evaluation | `.venv/bin/python hobby/hobbymac_run.py --model trained --round r4 --adapter r4 --runtime mlx` |
| Score a run | `.venv/bin/python hobby/hobbymac_score.py <run folder>` |
| Harness tests: 10-action parser and allow-list (no model) | `.venv/bin/python hobby/test_harness.py` |
| Hobby bar worker protocol: every request ends, errors included (no model) | `.venv/bin/python hobby/test_server.py` |
| System Settings agent parser tests (no model) | `.venv/bin/python hobby/test_offline.py` |
| Generate training data | `hobby/hobbymac_data.py` |
| Train an adapter on Modal (H100) | `modal run hobby/hobbymac_modal.py` |

The evaluation restores brightness, volume, appearance and windows after each trial. Calendar trials use a separate "Hobby Test"
calendar and never send invites.

## Repository layout

| Path | Contents |
|---|---|
| `hobby/` | App (`hobby_demo.py`), MLX and PyTorch runtimes, harness, checkers (`*.swift`), calendar tool, evaluation and training code |
| `data/` | Runtime adapter, retired sealed test sets, regex baselines, fixtures; the Swift tools and run logs are built here (git-ignored) |
| `docs/` | Training report, engineering and efficiency write-up, Calculator report, demo script |
| `assets/` | Figures |
| `models/`, `vendor/` | Created by `setup.sh` (git-ignored) |

## Licence and credits

- **Licence:** Apache-2.0.
- **Credits:** Built by Hariharan and Prabhurajhan at Fuel Labs. Architecture based on HobbyLM by Harish.
- **Dependency:** `mediar-ai/mcp-server-macos-use` is downloaded by `setup.sh`, not bundled.
  - **Its licence:** Business Source License 1.1, with the Additional Use Grant "Production use is permitted for non-commercial,
    educational purposes only". It converts to MIT on 2028-04-09.
  - **Commercial use** needs a licence from Mediar.
- **Related work:** UC Berkeley's TinyAgent.
