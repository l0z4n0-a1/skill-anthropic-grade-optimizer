# anthropic-grade-optimizer

[![CI](https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

A Claude Code skill that reviews a Claude Code setup as a system: what loads,
what it costs, what gets used, whether each piece is the right kind of piece,
and whether each is well made for its job. Findings cite Anthropic's
documentation with a verbatim quote, and changes are measured before and after.

It is an independent project and is not affiliated with Anthropic.

## What it adds to what Claude Code already has

Claude Code ships good checks, and this skill uses them instead of repeating
them:

| Built in | Covers |
|---|---|
| `/doctor` | Installation health, invalid settings, unused extensions, derivable CLAUDE.md content |
| `/doctor prompt-audit` | Instruction text written for older models, stale references, files that contradict each other |
| `/usage` | Recent usage attributed to skills, subagents, plugins and MCP servers |
| `/context all` | What is in the context window right now |

Those look at one thing at a time. This skill looks at how the pieces work
together and whether each is good at what it is for:

- **Placement.** A rule that must always hold is written as prose when it should
  be a hook; a monthly procedure sits in the file every session loads; the model
  does by reasoning what a script would do exactly.
- **Feedback.** Whether the model has a check it can run to know its work is
  done, and how strictly completion is enforced.
- **Economy.** What every session pays in fixed context, set beside what was
  actually used in the last 30 days; what one run of each subagent costs; how
  often a session paid again for context it already held, and why.
- **Routing.** Whether the model can tell your skills and subagents apart from
  their descriptions.
- **Allocation.** Whether each role runs on a model and effort level that suits
  its work.
- **Fitness.** Whether a skill or subagent would produce good work, not only
  whether its frontmatter is valid.
- **Model fit.** What to change, remove and add when the model reading the setup
  changes.

## How it works

Three parts, each doing what it is good at.

```
scripts/measure.py     counts: pieces, load timing, context cost, 30-day usage
kb/claims/*.jsonl      remembers: 822 statements from Anthropic's docs, each
                       with a verbatim quote, source and read date
SKILL.md + references  judges: the model reads the setup with the measurement
                       and the relevant claims, and reports findings
```

Scripts do everything that can be counted, so no number in a report is a guess.
The knowledge base holds what a model could get wrong from memory: how the
harness behaves, what each current model needs, what Anthropic recommends and
why. Judgment is left to the model, because whether a subagent's brief is good
enough is not something a rule list can settle.

Every claim's quote is checked against a snapshot of its source by
`scripts/kb_gate.py`. A claim whose quote is not found is rejected, which is
also how the knowledge base finds its own stale entries after the documentation
changes.

## Install

```bash
git clone https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer.git ~/.claude/skills/anthropic-grade-optimizer
```

Python 3.9 or later, standard library only. Then, in Claude Code:

```
review my Claude Code setup
```

or name the skill: `/anthropic-grade-optimizer`. You can also ask for one piece
("review this subagent") or a migration ("fit my setup to Opus 5.5").

## The measurement on its own

```bash
python scripts/measure.py --project . --out before.json
# ... change things, work for a while ...
python scripts/measure.py --project . --compare before.json
```

It reads local files only and makes no network call. It copies values only from
fixed lists of fields that are configuration (named frontmatter fields, named
settings, named hook options) and records everything else by name or count.
Hook commands are copied as written. From session history it keeps counts, token
totals and the names of models, tools, skills and agents, never message text. Token figures for
files are character counts divided by four and are labelled as estimates. What
it cannot see (the built-in system prompt, MCP tool definitions, sessions from
other machines) is listed in its output under `not_measured`.

## Knowledge base

```bash
python scripts/kb.py core                        # the review questions and the principle behind each
python scripts/kb.py core placement              # the dozen claims to read first for one question
python scripts/kb.py show hooks,settings --brief # everything on a topic, one line per claim
python scripts/kb.py model claude-opus-5-5       # everything tied to one model
python scripts/kb.py cite hooks-030              # full record with quote and source
```

Sources are Anthropic's Claude Code documentation, the Claude platform
documentation, the reference files of the `claude-api` skill bundled with Claude
Code, and Anthropic engineering posts: 77 sources, last read 2026-11-14. The
documentation itself is not redistributed; the repository holds short quotes,
links and content hashes.

Updating for a new model or a Claude Code release is a four-step loop described
in [references/maintaining.md](references/maintaining.md).

## Calibration

`evals/` builds two throwaway setups: one with ten planted defects and an answer
key, one with nothing wrong that matters. Running the review against both gives
the two numbers that decide whether a reviewer can be trusted: how many real
defects it finds and how many it invents. Results by model are recorded in
[evals/README.md](evals/README.md).

## Limits

- The review is a model's judgment, informed by measurement and cited claims. It
  can be wrong, and each finding says how sure it is and how to check it.
- Usage figures come from this machine's session history and cover only the
  retention window Claude Code keeps.
- The knowledge base is as current as its last fetch. A model released after
  that date is not covered until the loop is run.

## Version 1

Version 1 was a rule engine that scored single artifacts against 189 cited
rules. Claude Code now ships `/doctor prompt-audit` for line-level review, so
version 2 moved to the system-level questions it does not ask. Version 1 remains
available at the `v1.0.0` tag.

## License

MIT. See [LICENSE](LICENSE).
