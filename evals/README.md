# Calibration

A reviewer is worth trusting when it finds the defects that are there and does
not report ones that are not. These files measure both.

## What is here

- `build_fixtures.py` writes two throwaway Claude Code setups into a directory
  you name. `planted` has ten defects, each a specific mistake that a cited
  claim says is one. `clean` is a small setup built to have nothing wrong that
  matters.
- `ANSWER-KEY.md` lists the ten defects with the claims behind each, what in
  `planted` is deliberately sound, and how to score a run.

## Running it

```bash
python evals/build_fixtures.py <new empty directory>
```

Use a fresh directory under your system's temporary folder (`/tmp/...`,
`%TEMP%\...`) each time: the builder overwrites `planted` and `clean` inside
the directory it is given. It takes that one argument and no options, and
exits 0 when the fixtures were written and 2 on anything else.

Then, in a fresh Claude Code session with the plugin loaded, once for each
setup:

```
Review the Claude Code setup whose user-level directory is
<directory>/planted/home/.claude and whose project is
<directory>/planted/project. Do not change anything in it.
```

The reviewer must not be able to read `ANSWER-KEY.md` or the builders. Starting
the session elsewhere is not enough, because the loaded plugin's own directory
holds them, and a copied checkout keeps them in its git history. Export the
plugin without git metadata and without `evals/`:

```bash
mkdir <copy>
git archive HEAD -- . ':!evals' | tar -x -C <copy>
```

Load that copy with `claude --plugin-dir <copy>` and start the session in a
directory that is neither the copy nor this repository. The reviewer can
still read anything on the machine its permissions allow, this repository
included; deny reads of it in the session's permissions (`Read(<this repo>/**)`
under `deny`) or run the round from a machine or user without it. Record with each
result: the commit the copy was made from, the exact model id, and how it was
scored. Score each report against the key. A run produces three numbers: defects found
out of ten on `planted`, false findings on `planted`, and findings presented as
significant on `clean`.

One run is one sample. The same model on the same setup will not produce the
same report twice, so treat a difference of one defect between two runs as
noise, and repeat before concluding that a change to a guide helped or hurt.

## Recorded results

Each row is a single run, scored by hand against the key.

| Date | Skill version | Model | Found on `planted` | False on `planted` | Significant on `clean` |
|---|---|---|---|---|---|
| 2026-11-15 | 2.0.0 | Claude Opus 5.5 | 10 of 10 | 0 | 1, a real defect in the fixture (see the answer key); fixture since changed |
| 2026-11-15 | 2.0.0 | Claude Haiku 5.5 | 7 of 10 (missed D4, D7, D8) | 0 | not run |
| 2026-11-15 | 2.0.0 | Claude Opus 5.5 | not run | not run | 1, again a real defect in the fixture (second entry in the answer key); fixture changed again |

| 2026-11-27 | 2.1.0 | Claude Sonnet 5.5 | 10 of 10 | 0 | not run |
| 2026-11-27 | 2.2.0 | Claude Sonnet 5.5 | (upgrade runs, below) | | 0 in 3 runs |

The 2.1.0 row is the run published unedited in
[docs/example-report.md](../docs/example-report.md). The 2.2.0 `clean` figure
comes from the three upgrade runs below: each began with a full review of the
current `clean` setup, found nothing worth changing and stopped without an
edit. That is the first recorded result on `clean` with no significant
finding. Both earlier attempts at writing it contained a real problem, and the
review found it each time.

## Upgrade calibration

`/grade-optimizer:upgrade` runs unattended on a fresh `planted` copy, with
"apply all, including deletions and user-level changes", from a plugin copy
without `evals/` or `tests/`. Then three checks, none of them the upgrader's
own word:

- `python evals/check_upgrade.py <dir>/planted`: a deterministic oracle, one
  check per defect, run on the edited files. It exercises the guard with
  five commands (three pushes to main it must block, two branches containing
  the word it must let through) and checks the rest by structure. On a fresh
  build every defect reads "not fixed"; on a hand-fixed copy in its tests,
  every one reads "fixed". It also checks that what the key lists as sound
  survives, and that every file no defect touches is unchanged.
- A blind review of the result in a new session, which sees only the edited
  setup, to catch what the upgrade broke or only half fixed.
- The same upgrade on a fresh `clean` copy, where the right result is no edit.

All runs: 2026-11-27, Claude Sonnet 5.5, scored by the final oracle.

| Run | Guides | Fixed (oracle) | Not fixed, and why | Sound kept | Edits outside the fixture | Edits on `clean` |
|---|---|---|---|---|---|---|
| 1 | first draft | 6 of 10 | D1, D2: the rewritten guard missed `git -C . push origin main`. D4, D9: held, with a question | 5 of 5 | 0 | 0 |
| 2 | + test guards like a bypasser; read the capabilities guide | 6 of 10 | D6: judged not worth its risk. D10: moved max to high, still the top tier. D4, D9: held | 5 of 5 | 0 | 0 |
| 3 | + `settings_edit.py` | 8 of 10 | D4, D9: held, with a question | 5 of 5 | 0 | 0 |

D4 and D9 were held in every run, each time with the question that blocks
them: what `helper` is for, and whether `format_changed.py` was removed on
purpose. Rewriting a description without knowing the agent's job, or deleting
a hook the person may rely on, is the guess the command is told not to make,
so these count as not fixed but are the behavior wanted.

What the blind reviews found after each run. No run lost a sound rule or broke
a working piece. Run 3 introduced one defect: the rewritten guard parsed git
options from a list that included one git does not have and misread
`--signed`, and it let `git push origin HEAD` through while `main` was checked
out. The guide now says to write the smallest guard that covers the rule and
to block where it cannot tell; that change has not been run yet. The reviews
also kept raising what an upgrade cannot settle alone: two staging procedures
that may differ on purpose, a hook that protects one machine where the rule
is the project's, branch protection on the server.

Three runs on one model are a small sample, and the guides changed between
them; read the rows as the record of what each change fixed, not as a rate.

The model-fit job was run once, blind, on `planted` (Claude Opus 5.5, moving a
setup from Opus 5.5 to Sonnet 5.5). It produced the three lists the guide asks
for, cited a claim for each item, and declined to compute a saving from prices
the knowledge base does not hold. It has no answer key, so it has no score.

Both `planted` runs also reported observations outside the key that were true
of the setup and labelled as judgment (the main session's context size; trying a
smaller default model). Those are not counted as false. The three defects the
smaller model missed are all found by reading a piece's body closely, which is
the last of the review's questions and the first to be cut short.

## Process calibration

`references/process-review.md` has its own pair of fixtures. `python evals/build_process_fixtures.py
<new empty directory>` writes `process-planted` (ten defects, four things that are sound) and
`process-clean`, each a small orchestration process with a README, a runner, a gate and the records
of 50-odd past runs; the records come from a seeded generator, so the counts in the last section of
`ANSWER-KEY.md` are exact and the build is identical every time. Run it as above, once per fixture,
with the same reviewer copy and from a directory outside it, with a request such as "Review the
orchestration process in <directory>/process-planted. Do not run or change anything in it." Score against the
key: defects found out of ten on `process-planted`, false findings on `process-planted`, and
false findings on `process-clean`. The same caveat holds: one run is one sample. On `process-clean`
the target is 0 false findings, not 0 findings. Two kinds of error are counted, in separate columns:
a finding that does not hold against the code or the records (false), and a finding that presents as a
defect a cost the key lists as a residue of a sound process (residue as defect). The target is 0 in
both; the table shows rounds 2 and 4 missed it on the second. A
true finding the key does not know, that the owner of the process would change, is a defect of the
fixture: fix it in the builder and recompute the counts in the key; if the owner would not change it,
add it to the key's residues.

Five blind rounds on the process guide, all on 2026-11-27, each with a reviewer that did not see the
key (the reports name `claude-sonnet-5-5`). Rounds 1 and 2 are scored from the coordinator's counts;
round 3 was scored against the key by recounting the claims on the built records; rounds 4 and 5
were scored against the key from the reports, without recounting.

| Round | Found on `process-planted` | False on `process-planted` | `process-clean`: false | `process-clean`: new, true and fixed | `process-clean`: true but a residue, presented as a defect |
|---|---|---|---|---|---|
| 1 | 8 of 8 (the fixture then had 8 defects) | 0 | 1 of the 8 presented was not true | 7 (6 fixed; the unmeasured reviewer kept as a residue) | not split |
| 2 | 10 of 10 | 0 | 0 | 1 | 3 |
| 3 | 9 of 10 (P10 missed; P4's third part, the report in the reviewer's prompt, also not named) | 0, and 1 wrong aside (`unittest discover` with no tests exits 0; on Python 3.12 it exits 5) | 0 | 3, fixed (`scope` blind to added records and files; baseline and checks not sealed; per-stage tokens, dead reason and timeouts missing, in part: no verdict files before October and no release record stay residues) | 1 (the reviewer never measured) |
| 4 | 8 of 10 (P1 and P10 missed) | 1 (the second reviewer reported as unproven, which the key lists as sound) | 0 | 1, not fixed: value criteria a script could decide (order, uniqueness, date format) are left to the reviewer; listed as open in the key | 2 (the reviewer's count-and-first-id feedback; an executor that fills values instead of stopping) |
| 5 (planted only, guide revised after round 4) | 9 of 10 (P1 named from the code without the count the key requires; P10 scored on the code path, its 2 rounds in the records not found) | 0 | not run | not run | not run |

Round 4 ran after `process-review.md` and `foundations.md` were revised in answer to an outside
critique, and it scored below round 3. The false finding traced to a sentence that revision had
tightened: a second reviewer was to be justified against "the first one tuned", which no record can
show, so any second reviewer became reportable. The sentence now says what evidence in the records
settles it. Two general questions were also added (runs stopped early for no progress; a reviewer
that fails without judging). Those edits were made knowing what round 4 missed, so a later round on
this fixture is not an independent measure of them; a fixture the guide's author has not seen is.

Rounds 1 and 2 led to changes in the fixture and in the guide, so the rows are not repeated measures
of the same object: the `process-clean` of round 3 is not the one of round 1, and the guide was
rewritten between rounds 2 and 3 to separate a defect from a cost, which is why the costs of round 2
that were overstated came back as costs in round 3. Read the rows as a sequence, not as a trend.
