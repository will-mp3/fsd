# fsd

Full Self Driving, not for vehicle use.

A macOS computer-use harness project for operating desktop applications from
pixels under per-application approval. The current CLI checks the environment,
lists applications, and manages persisted approvals.

Design: [computer-use harness specification](docs/the-ark/specs/2026-10-03-computer-use-harness-design.md).

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
