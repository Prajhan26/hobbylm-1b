# HobbyLM-1B × macos-use: System Settings navigation experiment

Hypothesis under test: *an unchanged local 1B model can use macOS accessibility observations and action feedback to
complete bounded desktop navigation tasks.*

## Identities
| Thing | Value |
|---|---|
| Model | HobbyLM-1B **Instruct**, Apple MLX release, `work/hobbylm-1B-mlx-release/` (`model.safetensors` sha256 `18382d789b8348f17008b188482ec7b039e597a8d80161b023f2788f10c0a150`; partial 8-bit routed-expert down-projections in layers 10–19, rest FP32) |
| Runtime | the release's own bundled `runtime/mlx_hobbylm` (hashes checked against the release `SHA256SUMS.txt` at every start); MLX 0.32.3, Transformers 5.17.0, `.venv-mlx-release` |
| Not used | the repository's top-level `mlx_hobbylm/` (has uncommitted local edits); HobbyLM-1B **base** (`6a619788…1674`) is not on disk and was excluded rather than downloaded |
| Tokenizer | GPT-2 BPE from the release (`tokenizer_config.json` sha256 `2a199fc0…619f`), EOS 50256 |
| Prompt format | training-native literal `SYSTEM:/USER:/ASSISTANT:` (frozen after dev; see `work/macos-agent/frozen/prompt.json`) |
| Decoding | greedy, ≤16 new tokens, prompt+output ≤1,024 tokens enforced (over budget raises; never truncated) |
| macos-use | `mediar-ai/mcp-server-macos-use` commit `205c8880e8c06fa96a3e3a859e6edca728eb6c47`, server `SwiftMacOSServerDirect 1.6.0`, built locally (`swift build -c release`; binary sha256 `c7927a91…c655`); MacosUseSDK `a2d78663…`, swift-sdk `0.12.1` |
| OS | macOS 15.5 (24F74), MacBook Air |

## Setup (manual steps; nothing is granted automatically)
1. System Settings → Privacy & Security → **Accessibility** → enable the app that launches the runner (here: Visual Studio Code). Restart it. Screen Recording is used only for macos-use's own screenshots.
2. Build the server: `cd work/macos-agent && git clone https://github.com/mediar-ai/mcp-server-macos-use && cd mcp-server-macos-use && git checkout 205c8880e8c0 && swift build -c release`
3. Build the checker: `swiftc -O backend/capability/macos_agent/checker.swift -o work/macos-agent/checker`
4. Offline tests (no screen actions): `python3 backend/capability/macos_agent/test_offline.py`
5. One trial: `.venv-mlx-release/bin/python backend/capability/macos_agent/run.py --task H01 --condition B`
6. Score: `python3 backend/capability/macos_agent/score.py`; order test: `.venv-mlx-release/bin/python backend/capability/macos_agent/order_test.py`

**Interrupt:** press **Esc** during an action (macos-use InputGuard), `touch work/macos-agent/STOP` (checked before every action), or Ctrl-C.
Revoke the Accessibility permission when finished.

## Who does what
- **Model (HobbyLM):** every action: `OPEN System Settings`, `CLICK <exact visible name>`, `SCROLL UP|DOWN`, `DONE`, `UNKNOWN`.
- **Harness (`agent.py`, `run.py`):** goal-independent compaction (window title, 4 lines of page text, sidebar items found by
  geometry inside the `AXOutline "Sidebar"` box, Back/Forward buttons); maps an exact, unique visible name back to that control
  with fresh coordinates; rejects anything else; executes valid actions through macos-use; enforces scope and stop rules.
  It never sees the goal when building observations, never chooses a target, never retries a failed output.
- **Checker (`checker.swift`):** reads System Settings' selected sidebar row directly from the Accessibility API, read-only.

## Scope limits
Only System Settings can be opened. Only sidebar items and Back/Forward get names the model can click; content-area controls
(switches, pop-ups, fields, buttons) are never clickable, so no setting can change. No typing, keys, scripts or other apps.
Stops: 10 proposals, a repeat after no change (executed or rejected), a sheet dialog or app switch, an out-of-scope proposal,
STOP/Ctrl-C, or destination reached while the model proposes another action (not executed).

## Files
- `work/macos-agent/frozen/` — tasks (+ amendment 1: completion check), frozen prompt
- `work/macos-agent/runs/<set>-<task>-<condition>-<time>/` — `trial.json` (per step: compact observation, full prompt user turn, token counts, latency, raw output, parse, validation, execution result), raw `obs_*.txt`, screenshots before/after
- `work/macos-agent/heldout-score.json`, `order-test.json`, report `docs/HOBBYLM_MACOS_NAVIGATION_2026-10-20.md`
