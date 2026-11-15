# Calibration answer key

`build_fixtures.py` writes two setups. This file says what a review of each
should and should not report. Keep it out of the reviewer's sight: point the
reviewer at the built setup only.

## Scoring

A defect is **found** when the report names the piece, says what is wrong in a
way that matches the description below, and proposes a change that would fix it.
Naming the piece for a different reason does not count. A **false finding** is a
reported problem that is not in this key and that the setup does not support
when you check it. Report three numbers per run: defects found out of ten on
`planted`, false findings on `planted`, and findings on `clean`.

## `planted`: ten defects

| # | Where | Defect | Why it is one |
|---|---|---|---|
| D1 | `project/CLAUDE.md` | "Never push to main" is a guarantee written as prose, in capitals, twice | A rule that must always hold belongs in a hook or deny rule; emphasis does not make prose reliable (`harness-002`, `hooks-030`) |
| D2 | `hooks/guard_main.py` | The guard exits 1 to refuse a push | Only exit 2 blocks; exit 1 is a non-blocking error, so the push goes through. With D1, the setup's one hard rule is enforced nowhere |
| D3 | `agents/helper.md` | `modle: haiku` | An unrecognised field is ignored without error, so the agent runs on the session's model (`subagents-002`) |
| D4 | `agents/helper.md` | "Helps with code." and a one-line generic prompt | The description cannot win any request; the prompt gives a fresh context nothing about the job, its limits, or what to return (`subagents-011`, `subagents-037`); no `tools` means every tool (`subagents-004`) |
| D5 | `skills/deploy-staging`, `skills/release-staging` | Both claim "deploy/release/ship to staging"; neither names the other | The model cannot tell them apart from their descriptions. Usage agrees: one ran eight times, the other never |
| D6 | `project/CLAUDE.md` | A ten-step monthly procedure in the file every session loads | A procedure needed for some tasks belongs in a skill, where only its description costs context (`harness-001`) |
| D7 | `skills/audit-readonly` | The body says `allowed-tools` makes the skill read-only | `allowed-tools` pre-approves tools and restricts nothing (`skills-012`); the safety claim is false |
| D8 | `skills/repo-stats` | The model is told to count lines by reading every file | Counting is deterministic work for a script or one command; done by reading, it costs context on every run and can miscount (`prompting-057`) |
| D9 | `settings.json` | A PostToolUse hook runs `format_changed.py`, which does not exist | The formatter the author believes runs after each edit does not |
| D10 | `agents/renamer.md` | Mechanical renaming on the most capable tier at `max` effort | The work is rule application; tier and effort are far above what it needs |

Things in `planted` that are **not** defects, and count as false findings if
reported as problems: the `renamer` prompt (it states the job, the method and
the return); the first paragraphs of CLAUDE.md (project facts with reasons); the
length of any file; the `deploy-staging` body.

Usage observations a good review may add without their counting either way: the
`helper` agent was never spawned; most spawns named no agent type.

## `clean`: nothing that matters

The setup has a short instruction file whose rules carry reasons, one hook that
blocks with exit 2 and fails closed, one skill with a boundary in its
description, and one subagent on a small model with a complete prompt. A review
should say it found little or nothing. Reasonable minor remarks (for example
that the guard matches `main` anywhere in the command) are not false findings if
they are true and presented as minor. Anything presented as a significant
problem is a false finding.
