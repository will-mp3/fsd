# fsd

Full Self Driving, not for vehicle use.

A macOS computer-use harness for a vision-capable agent, aiming to understand
and operate varied on-screen environments from pixels under per-application
approval. The CLI checks the environment, manages persisted approvals, and runs
an interactive agent session with `fsd chat`.

Current design: [hosted vision operator](docs/the-ark/specs/2026-10-11-hosted-vision-operator-design.md).
Implementation: [Plan 2](docs/the-ark/plans/2026-10-11-hosted-vision-operator.md).
The operator uses one hosted vision-language model through OpenRouter, selected
in internal configuration. Tasks 1 through 6 are implemented; Task 7 covers live
integration and model capability evaluation. OCR, detectors, and separate decision
models are optional optimizations to evaluate after establishing the baseline.

Foundation and historical architecture: [original specification](docs/the-ark/specs/2026-10-03-computer-use-harness-design.md).

## Requirements

- macOS 14 or newer
- Python 3.12 or newer and `uv`
- Screen Recording and Accessibility permission for the terminal running `fsd`

## Usage

```bash
uv sync
uv run fsd doctor
uv run fsd apps list
uv run fsd apps approve TextEdit
uv run fsd apps block TextEdit
```

`doctor` reports backend capabilities and missing permissions, including where
to grant them. `apps list` shows approval state, display name, bundle identifier,
and a running or system label.

Approve or block an app by its exact bundle identifier or a unique display name
(case-insensitive). If a name matches multiple apps, use a bundle identifier:

```bash
uv run fsd apps approve com.apple.TextEdit
```

Every app, including system surfaces, is blocked until explicitly approved.
Approvals are stored in `~/.config/fsd/approvals.json` by default. Set
`FSD_CONFIG_DIR` to override the directory, or `XDG_CONFIG_HOME` to use
`$XDG_CONFIG_HOME/fsd/approvals.json`. `FSD_CONFIG_DIR` takes precedence.

Exit statuses are `0` for success, `1` when `doctor` finds missing permissions,
and `2` for reported errors or invalid command syntax.

## Interactive session

Set `OPENROUTER_API_KEY` in your environment, approve the applications you want
the agent to use, and make the starting application visible. Then run:

```bash
uv run fsd chat
```

The model is configured centrally in `src/fsd/operator/config.py`; no model
argument is required. The agent acts autonomously toward your goal and reports
progress. Completing, failing, or canceling a task returns to the conversation
prompt, where you can enter a follow-up goal.

When the agent needs help, give guidance or manually adjust the screen and enter
`/continue`. Use `/cancel` at a help prompt or Ctrl-C in the terminal during a run
to cancel the current task. Terminal Ctrl-C is not a global desktop hotkey.
At a budget-limit prompt, `/extend` explicitly grants another execution budget.
Use `/exit` or EOF at a goal or help prompt to end the session; exiting from a
help prompt also cancels the current task.

Task context lasts for the current process only. Closing fsd does not save a
resumable session. Captured images sent to the configured hosted model contain
approved applications only. Model performance and completion reliability still
need live evaluation on your tasks.

To append timing, action-type, and token/cost metrics to a JSONL file:

```bash
FSD_METRICS_PATH=./metrics.jsonl uv run fsd chat
```

The parent directory must already exist. Each record is flushed as it is
written. Records exclude screenshots, task text, typed text, and API keys;
they do not restore a session or establish whether a task succeeded. File
errors stop chat with exit status `2` and a diagnostic message.

## Development

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Live tests require OS permissions and touch the real desktop, including briefly
activating Finder and restoring the previously active app:

```bash
FSD_LIVE=1 uv run pytest -q
```
