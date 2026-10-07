# fsd

## Critical Rules

- I type all code myself (apart from exempt list below). Do NOT use Edit/Write/NotebookEdit on source/implementation files. 
- Present each change as a code block with its file path and enough surrounding context for me to place it, then stop and let me type and test it. This overrides and "write the file" step in a skill or workflow.
- EXEMPT: test files, non-code artifacts such as memory files, docs, config, and generated/vendored output.
- Design explanation should come before, during, and after implementation code. Explanation should be viewed as part of the implementation, not an accessory.
- Each implementation should come with followup questions to ensure understanding.

## Source of truth

Project specifications and implementation plans live here:

- Specifications: `docs/the-ark/specs/`
- Implementation plans: `docs/the-ark/plans/`

Use the relevant documents there as the project evolves.

## Load-bearing architecture

- `Platform` is the only contract between the harness and the operating system. Everything above `fsd.platform` is unaware of the OS; the single `sys.platform` check lives in `src/fsd/platform/__init__.py`.
- Filtered capture and window-owner lookup are mandatory backend capabilities. Without either, refuse to run; there is no warning mode.
- Every app is blocked until explicitly approved. Enforcement has two points: the capture filter and the action gate.
- All input goes through `ActionGate`, which checks ownership immediately before each action and performs it only if approved. Never call `Platform` input methods directly from above the gate.
- The agent's input is pixels only. The accessibility tree is evaluation ground truth, never agent input.
- `Platform` operations are synchronous; use asyncio for the network calls (inference server, Jev, planner).
- Preserve a clean engine/CLI boundary: the loop has no terminal dependencies and the CLI consumes its events.

## Project shape

Use Python 3.12+, `uv`, and a `src/fsd/` package layout. macOS only in v1; `pyobjc` dependencies carry a `sys_platform == 'darwin'` marker so the package installs elsewhere.
