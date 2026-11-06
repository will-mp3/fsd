# fsd

## Critical Rules

- I type all code myself (apart from exempt list below). Do NOT use Edit/Write/NotebookEdit on source/implementation files. 
- Present each change as a code block with its file path and enough surrounding context for me to place it, then stop and let me type and test it. This overrides and "write the file" step in a skill or workflow.
- EXEMPT: test files, non-code artifacts such as memory files, docs, config, and generated/vendored output.
- Design explanation should come before, during, and after implementation code. Explanation should be viewed as part of the implementation, not an accessory.
- Provided test cases should have their purpose described along with what they are testing for.
- Each implementation should come with followup questions to ensure understanding.

## Source of truth

Project specifications and implementation plans live here:

- Specifications: `docs/the-ark/specs/`
- Implementation plans: `docs/the-ark/plans/`

Use the relevant documents there as the project evolves.

## Load-bearing architecture

- `Platform` is the only contract between the harness and the operating system. Everything above `fsd.platform` is unaware of the OS; the single `sys.platform` check lives in `src/fsd/platform/__init__.py`.
- Main-display capture and window-owner lookup are mandatory backend capabilities. Without either, refuse to run; there is no warning mode.
- Capture the full main display, including unapproved apps and actual occlusion. Every app is blocked for input until explicitly approved; ActionGate enforces input authorization.
- All input goes through `ActionGate`, which checks ownership immediately before each action and performs it only if approved. Never call `Platform` input methods directly from above the gate.
- Visual input is pixels, accompanied by app ownership and input-approval metadata. The accessibility tree is evaluation ground truth, never agent input.
- For observation, app identity, and explanation recording, follow `docs/the-ark/specs/2026-11-05-observation-and-explanations-design.md`; its approved policy supersedes older filtering and identity-hiding requirements.
- `Platform` operations are synchronous; use asyncio for the network calls (inference server, Jev, planner).
- Preserve a clean engine/CLI boundary: the loop has no terminal dependencies and the CLI consumes its events.

## Project shape

Use Python 3.12+, `uv`, and a `src/fsd/` package layout. macOS only in v1; `pyobjc` dependencies carry a `sys_platform == 'darwin'` marker so the package installs elsewhere.
