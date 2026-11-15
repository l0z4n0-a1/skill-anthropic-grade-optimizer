# Keeping the knowledge base current

The knowledge base is the part of this skill that ages. Claude Code ships
changes every week and a new model changes what good instructions look like.
The skill's method does not need to change when that happens; the claims do.
Updating them is a loop of four steps, and three of the four are scripts.

## When to run it

When a new Claude model ships, when Claude Code releases something that changes
how skills, subagents, hooks, memory or settings behave, or when a review turns
up a claim that contradicts what Claude Code now does.

## The loop

**1. Add new sources.** `kb/sources.json` lists every page the knowledge base
draws on. For a new model, add its prompting guide, its what's-new page and its
migration guide. The index pages list what exists:

```
python scripts/kb_fetch.py --list https://platform.claude.com/llms.txt
python scripts/kb_fetch.py --list https://code.claude.com/docs/llms.txt
```

Each entry has an `id`, a `url` (or `bundled`, for a file of the `claude-api`
skill that ships with Claude Code), a `tier` (1 for official documentation, 2
for Anthropic engineering posts) and a `topic`.

**2. Fetch.** `python scripts/kb_fetch.py --bundled-dir <claude-api skill dir>`
downloads every source into `kb/snapshots/` and prints which ones changed since
the last run, by content hash. Snapshots are other people's documentation, so
they stay out of git; `kb/snapshots.lock.json`, which records the hash and date
of each, is committed. The bundled directory is printed as "Base directory for
this skill" when the `claude-api` skill loads in a session.

**3. Find what went stale.** `python scripts/kb_gate.py` checks every claim's
quote against the fresh snapshot. A claim whose quote is no longer there is a
claim whose source changed underneath it: the gate lists each one. For each,
read the new text and either correct the claim or delete it.

**4. Extract from what is new or changed.** Give the changed snapshots to a
model with `kb/EXTRACTION.md` as its brief. That file defines the record, the
bar for what counts as a claim, and what to send back. Extraction is the one
step that needs judgment; several extractors can run in parallel on different
sources as long as each is given its own id range. Then run the gate again. A
claim is in the knowledge base only once the gate passes.

Finish with `python -m unittest discover tests` and commit the claims, the lock
file and `sources.json` together.

## Why it is built this way

The gate is what makes the knowledge base trustworthy. A model summarising
documentation will sometimes state what it remembers instead of what the page
says, and for a tool whose whole value is being current, a confident stale claim
is the worst failure. Requiring a verbatim quote that a script can find turns
that failure into an error message. The same check, run after a fetch, finds
claims that were true when written and no longer are.

Claims carry the model ids their source names, so guidance for one generation
does not leak into reviews for another, and retiring a model is deleting the
claims tied only to it.

Nothing about a specific model is written into `SKILL.md` or the review guides.
If you find yourself adding a model name there, it belongs in a claim.
