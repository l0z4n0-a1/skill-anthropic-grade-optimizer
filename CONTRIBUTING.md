# Contributing

Thanks for the interest. Two rules shape this project, and contributions that
keep them are welcome.

## The two rules

**A claim quotes its source.** Everything in `kb/claims/` carries a verbatim
quote and a source id, and `scripts/kb_gate.py` rejects a claim whose quote is
not in the source snapshot. A pull request that adds or edits claims must pass
the gate. [kb/EXTRACTION.md](kb/EXTRACTION.md) describes the record and the bar
for what counts as a claim.

**Scripts count, the model judges.** If something can be counted or checked
exactly, it belongs in a script with a test. If it needs reading and judgment,
it belongs in `SKILL.md` or a guide under `references/`, written as an
explanation of how to think about the question, not as a rule to match.
Nothing about a specific model goes in the guides; that belongs in a claim.

## Local setup

```bash
git clone https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer.git
cd skill-anthropic-grade-optimizer
python -m unittest discover tests
```

Python 3.9 or later. There are no dependencies to install.

To check quotes you need the snapshots, which are not in the repository because
they are Anthropic's documentation:

```bash
python scripts/kb_fetch.py --bundled-dir <claude-api skill directory>
python scripts/kb_gate.py
```

The bundled directory is printed as "Base directory for this skill" when the
`claude-api` skill loads in a Claude Code session. Without it, the sources
marked `bundled` fail to fetch and the gate reports their claims as unchecked.

## Updating the knowledge base

Follow [references/maintaining.md](references/maintaining.md). Commit the
claims, `kb/sources.json` and `kb/snapshots.lock.json` together.

## Changing the measurement

`scripts/measure.py` must stay standard-library only, make no network call, and
never write a value from `env` or text from a session into its output. Add a
test in `tests/test_instrument.py` for any new figure, built on the temporary
setup the tests create, so the suite never reads a developer's own files.

## Pull requests

Describe what changed for someone using the skill. For a change to a guide, say
what review behavior it is meant to change and how you checked that it did.
