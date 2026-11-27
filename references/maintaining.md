# Keeping the knowledge base current

The knowledge base is the part of this skill that ages. Claude Code ships
changes every week and a new model changes what good instructions look like.
The skill's method does not need to change when that happens; the claims do.
Updating them is the loop below. Scripts do the downloading, hashing and
quote checking; extraction and the second reading need a model, and those two
should not be the same model in the same context. `commands/update.md` is the
same loop written as numbered instructions for a session; where the two
differ, that file is the procedure and this one is the explanation.

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

Each entry has an `id`, exactly one locator, a `tier` and a `topic`. The
locator is a `url`; or `bundled`, for a file of the `claude-api` skill that
ships with Claude Code; or `path`, for a file relative to the repository
root. `docs/reference.md` has the full record and what the gate checks. Tier 1 is official
documentation. Tier 2 is what Anthropic publishes under its own name outside
the documentation: engineering and research posts, articles, repositories.
Tier 3 is a person from Anthropic speaking somewhere else, such as an
interview or a hosted conversation. A tier 3 claim opens by attributing the
statement to the speaker and reports what they said their team does; it is
never written as guidance, and a review that cites one says whose words they
are.

**2. Fetch.** Snapshots are other people's text, so they stay out of git;
`kb/snapshots.lock.json`, which records the hash and download date of each, is
committed. That gives two situations:

- *A fresh clone has no snapshots.* `python scripts/kb_fetch.py --bundled-dir
  <claude-api skill dir>` downloads every source into `kb/snapshots/`. The
  bundled directory is printed as "Base directory for this skill" when the
  `claude-api` skill loads in a Claude Code session; without it the six
  bundled sources are skipped and the gate reports their claims as unchecked.
- *A clone that already has them* is refreshed with `python
  scripts/kb_update.py --apply --bundled-dir <dir>`, after a plain
  `kb_update.py` has shown what changed.

Either way, a source whose bytes no longer match the lock is recorded in
`kb/pending.json` before the lock advances, and its previous snapshot is kept
in `kb/snapshots-prev/` when the local copy matched the lock. When it did not,
or there was none, as on a fresh clone, the report lists the source under
`no_previous`: there is no diff to read, so re-read the whole source against
its claims. A source with no lock entry yet is new and is not pending.

**3. Find what went stale.** `python scripts/kb_gate.py` checks every claim's
quote against the fresh snapshot, and the shape of every record, source and
lock. It exits 0 when everything was checked, 1 when a claim or a data file
failed, and 3 when the only problem is a missing snapshot. A claim whose quote is no longer there is a
claim whose source changed underneath it: the gate lists each one. For each,
read the new text and either correct the claim or delete it. The gate also
prints a warning for a claim whose sentence contains a number its source never
prints. A warning does not fail the gate, because a claim may compare its
source's figure with another page's, but each one is a claim to read again.

**4. Extract from what is new or changed.** Give the changed snapshots to a
model with `kb/EXTRACTION.md` as its brief. That file defines the record, the
bar for what counts as a claim, and what to send back. Extraction is the one
step that needs judgment; several extractors can run in parallel on different
sources as long as each is given its own id range. Then run the gate again. A
claim is in the knowledge base only once the gate passes.

**5. Have a second reader check what the gate cannot.** The gate proves each
quote is in its source. It does not prove the claim says what the source says,
and extraction drifts in predictable ways: an option becomes a rule, a
condition is dropped, a result on one benchmark becomes a statement about a
model, a sample configuration's model becomes `applies_to`, a `check` flags
something the source never called a problem. Give the new and corrected claims, or a
random sample of forty when there are more than forty, to a reader that did not
write them. For each claim it opens the snapshot at the quote, reads the
section, and answers supported, overstated, unsupported or wrong scope,
naming the field at fault and the source text that shows it. If more than
three of a sample of forty fail, treat the whole batch as unreviewed and have
every claim in it tightened to its source, then sample again. A new batch
enters `kb/core.json` only after this step.

To state a fidelity rate, give the same sample to two readers from different
model families, neither seeing the other's answers, and report the share that
neither faulted. One reader's rate is an upper bound, and comparing one
reader's rate before a fix with another reader's rate after it measures the
readers.

**Fetched is not reviewed.** The lock says which bytes were downloaded;
`kb/pending.json` says which of them nobody has read yet, and the two are
kept apart on purpose. While a source is pending, `kb.py` prints a notice
beside each claim that rests on it, and `kb_update.py` reports it as work even
though today's bytes match the lock. A quote that survives a change can still
have gained an exception in the next paragraph, so re-read every claim of a
changed source against the diff, not only the ones the gate lists.
`kb_update.py --reviewed <ids>` clears a source. It runs the gate itself and
refuses if the gate fails or a snapshot it would release is missing; whether
the second reader has answered is something no script can attest, so that
part is yours to do first and to record.

**After the loop.** Three small files depend on the claims, and the tests say
when one has fallen behind:

- `kb/core.json` names the claims, at most fourteen, that form the first read for each
  review question, with a one-sentence principle those claims support. When
  extraction adds a claim that states a principle better, or removes one the
  core names, revise the entry. Keep each core short; its purpose is to be
  cheap to read.
- `kb/harness.json` holds the numbers `measure.py` depends on, each with the
  claim that documents it. When the gate flags one of those claims, correct the
  number there.
- `evals/` builds a setup with planted defects and a clean one. After a change
  to the guides or a new model, run the review against both as
  `evals/README.md` describes, and compare with the last recorded result.

Finish with `python -m unittest discover -s tests -t .` and commit together:
the claims, `kb/sources.json`, `kb/snapshots.lock.json`, `kb/index.lock.json`,
`kb/pending.json` if anything is still pending, and any of the three files
above that changed.

## Why it is built this way

The gate is what makes the knowledge base trustworthy. A model summarising
documentation will sometimes state what it remembers instead of what the page
says, and for a tool whose whole value is being current, a confident stale claim
is the worst failure. Requiring a verbatim quote that a script can find turns
that failure into an error message. The same check, run after a fetch, finds
claims that were true when written and no longer are.

The second reader exists because a verbatim quote is necessary and not
sufficient. The first time a batch was checked this way, a large share of
claims that had passed the gate said more than their source did, and none of
them looked wrong on their own: each was a plausible sentence next to a real
quote. An auditor that cites an overstated claim hands the person a finding
with Anthropic's name on it that Anthropic did not write.

Two readers are asked for because their misses do not overlap. On the sample
of sixty taken for release 2.1.0, one reader faulted seven claims and the
other passed all sixty while noting four as close calls; none of the four was
among the seven, and all eleven objections held when checked against the
source. Forty-nine of sixty drew no objection from either. The eleven were
faults of scope, a dropped condition, or a `why` or `check` that went beyond
the cited page; none was contrary to its source. One sample shows that a
single reader misses things; it does not give a rate for the claims outside
it, nor show that two readers together miss nothing. So when citing the
knowledge base, read the quote before resting a finding on the claim's
wording.

Claims carry the model ids their source names, so guidance for one generation
does not leak into reviews for another, and retiring a model is deleting the
claims tied only to it.

Nothing about a specific model, and no number about Claude Code, is written
into `SKILL.md` or the review guides. If you find yourself adding one there, it
belongs in a claim.
