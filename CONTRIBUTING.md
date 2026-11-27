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
python -m unittest discover -s tests -t .
```

Python 3.9 or later (`python3` or `py -3` where `python` is not on the path).
There are no dependencies to install, and the tests need no network and never
read your own Claude Code files.

To try your checkout in Claude Code, start a session with
`claude --plugin-dir <path to the checkout>`.

### Checking quotes

The gate needs the source snapshots, which are not in the repository because
they are other people's text. Download them once:

```bash
python scripts/kb_fetch.py --bundled-dir <claude-api skill directory>
python scripts/kb_gate.py
```

Six sources are files of the `claude-api` skill that ships with Claude Code.
Its directory is printed as "Base directory for this skill" when that skill
loads in a Claude Code session. Without `--bundled-dir`, those six are not
fetched and the gate exits 3, naming the snapshots it could not find: the
other claims were checked, and the 135 that rest on the bundled sources were
not.

If a source changed since the lock was written, `kb_fetch.py` records it in
`kb/pending.json`. That is expected on a fresh clone and is not yours to
clear unless your change is the update itself.

To check only the file you edited, pass it: `python scripts/kb_gate.py
kb/claims/hooks.jsonl`. That is a quick look, not the gate; a pull request
needs the full run to exit 0.

## Adding or correcting a claim

1. Find the source in `kb/sources.json`, or add it (one of `url`, `bundled`
   or `path`; a `tier`; a `topic`), and fetch it with
   `python scripts/kb_fetch.py --only <id>`.
2. Write the record in the `kb/claims/` file for its topic, following
   [kb/EXTRACTION.md](kb/EXTRACTION.md). Its id is the prefix the other
   records in that file use and the next unused number; the gate rejects a
   duplicate id anywhere in the knowledge base.
3. Run the full gate.
4. Have someone or something that did not write the claim read it against the
   source, and say in the pull request who or what that was. A quote that is
   present does not show the claim says what the source says.
5. Commit the claim file with `kb/sources.json`, `kb/snapshots.lock.json`
   and, when they changed, `kb/index.lock.json` and `kb/pending.json`.

## Updating the knowledge base

Follow [references/maintaining.md](references/maintaining.md), or run
`/grade-optimizer:update evolve` in a session started with `--plugin-dir` on
your clone. The update works on a branch and pushes nothing.

## Changing the measurement

`scripts/measure.py` must stay standard-library only, make no network call, and
never write an `env` value, an MCP server argument or message text into its
output. A new value may be copied only by adding its key to one of the
allowlists at the top of the file. Add a test for any new figure, built on a
temporary setup the test creates. If the output changes shape, update
[docs/reference.md](docs/reference.md) and, when a consumer of the old shape
would break, raise `schema_version`.

## Changing a guide

A change to `SKILL.md` or a guide changes how reviews come out, and reading the
text will not tell you how. Build the calibration fixtures and run the reviews
against them, as [evals/README.md](evals/README.md) describes, before and after
the change. A revision made in answer to a critique goes through the blind
runs like any other: one such revision made a round worse here.

## Releasing

Raise `VERSION` and `version` in `.claude-plugin/plugin.json` together and add
the `CHANGELOG.md` entry. Users of the marketplace receive a release only when
the manifest version changes. Run `claude plugin validate .` before tagging.

## Pull requests

Describe what changed for someone using the plugin. For a change to a guide,
say what review behavior it is meant to change and how you checked that it
did.
