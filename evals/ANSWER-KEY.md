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

The setup has a short instruction file that gives the test commands and whose
conventions carry reasons, a formatter hook that never blocks and says so, one
skill with a boundary in its description, and one subagent on a small model
with a complete prompt. It states no rule that must always hold, so there is
nothing for a hook or a permission rule to enforce. A review should say it found little or nothing. A true remark
presented as minor is not a false finding. Before counting something presented
as significant as false, check it against the setup: if it is a real problem,
the fixture is wrong, and the fix belongs here.

That happened once. The first version of `clean` enforced the push rule with a
hook that looked for the words `git push` and `main` in the command. A review
tested it, showed that a bare `git push` from main passed and that a branch
named `maintenance` was blocked, and reported it as significant. The review was
right and the fixture was changed.

It happened a second time. The next version replaced the hook with a deny rule
for the literal command `git push origin main`, and kept a rule in the
instruction file that merged migrations are never edited. A review pointed out
that the migration rule was enforced nowhere, and an independent check showed
the deny rule missed a bare `git push`. Both were right. The present version
states no must-always rule at all, because writing a guard with no gap proved
harder than the fixture's purpose justifies.

## Process: `process-planted` and `process-clean`

`build_process_fixtures.py` writes two more fixtures, for `references/process-review.md`.
Each is a small orchestration process (a runner that composes a contract, starts an
executor, puts the work through checks and a reviewer in a loop, and keeps a
ledger; a release step; a gate) together with the records of past runs. The records
come from a seeded generator, so every count below is exact and the same on every
build. Keep this file out of the reviewer's sight: point the reviewer at the built
directory only, and tell it not to run or change anything in it.

### Scoring

The rules above apply, with ten defects. A defect that rests on the records (P1, P5,
P8, P10) is **found** only when the report gives the count it read from the ledger or the
verdicts, or one close to it; naming the design without having counted does not score.
Report three numbers per run: defects found out of ten on `process-planted`, false
findings on `process-planted`, and false findings on `process-clean`. Line numbers are
those of the built files.

On `process-clean` the target is 0 false findings, not 0 findings. A process that does
real work has costs that a reviewer can truthfully name, and three blind rounds in a row
found something true. A finding is **false** when the claim does not hold against the code
or the records (a count that does not recompute, a line that does not say what is claimed),
or when it presents as a defect something the residues below name as the cost of a sound
process. A true finding is one of two things. A **residue** is listed below; it is not
false, and a report that calls a residue significant overstates it, which is worth noting
and is not counted. A **new** true finding is put to one question: would the owner of the
process change it? If so it is a defect of the fixture: fix it in the builder, rebuild,
recompute the counts in this section and list it under "Found and fixed". If not, add it to
the residues with the reason. A report is judged on the false count and on whether it
separates what is a defect from what is a cost; a long list of residues called significant
does not score as a good review.

### `process-planted`: ten defects

55 runs in `records/ledger.jsonl`. 88 verdict files in `records/verdicts/` cover
35 of the 55 runs (the later ones; the earlier runs have a ledger row only). Outcomes:
23 closed, 14 limit, 10 stalled, 4 escalated, 4 dead.

| # | Where | Defect | Why it is one |
|---|---|---|---|
| P1 | `docket/run.py:122` (`if failed == previous:`) and the ledger | The loop decides "no progress" by comparing only the list of failed criterion ids. All 10 runs that ended `stalled` have equal id lists in their last two rounds. 9 of the 10 have verdict files, and in 6 of 9 the two verdicts describe different defects (the executor fixed one and exposed another); in the other 3 of 9 they describe the same defect. Of the nine runs that can be inspected, the loop stopped six that were still moving | judgment (the guide's loop paragraph); `verif-003` and `verif-004` show why a loop needs a stop test, no claim says how to compare rounds |
| P2 | `docket/run.py:104` and `docket/run.py:130` | The primary reviewer ends each verdict with a `LESSON:` line and the runner stores it in the ledger row (51 of 55 rows carry one; the 4 dead runs have an empty string). No code reads it: `lesson` appears in no `.py` file besides `run.py` lines 89, 104 and 130, and the executor's prompt is the contract plus the last rejection only | judgment; `verif-037` is adjacent (lessons are pruned so they stay worth running) but does not cover one nobody reads |
| P3 | `checks/accept.py:13` | `sys.exit(0)` after printing the tail of the test run: the check exits 0 whether or not the work was done. The ledger shows `accept` = pass in 128 of 128 rounds, and 7 of the verdict files show `accept: exit 0` above `FAILED (failures=n)` | `evals-002` (the null baseline must fail), `evals-001` |
| P4 | `docket/run.py:40` (the contract is written into the executor's workspace), `docket/run.py:100` (it is re-read from there each round, with no hash) and `docket/run.py:73` (the executor's own report is in the reviewer's prompt) | The reviewer judges with the executor's account in hand, against a contract the executor can edit, and nothing notices. The runner does record the edit and acts on nothing: `touched` lists `contract.json` in 8 rounds, in each as the only file changed (see P5c) | `verif-012` (criteria must live where the change under review cannot edit them), `longrun-001`, `longrun-021`, `evals-008` |
| P5 | the ledger and the verdicts (`records/`) | The records show the loop cannot repair what it rejects. (a) Of 77 rounds that were rejected and followed by another round, the next round passed in 13 of 77. (b) Of 71 rejected rounds that have verdict files, 51 of 71 put the defect in the contract or its check (47 contract, 4 check arguments), 17 in the work, 2 in the environment, 1 in form alone. 97 of the 105 rejected rounds had every check green. (c) Of 23 closed runs, 8 of 23 closed in a round whose only change was to `contract.json` (a criterion reworded or the `schema` check dropped) with the review re-run; each of the 8 verdicts says what changed. The place to look is upstream of the executor, not a fifth round | `verif-053`, `plat-052` (a criterion that does not apply is not a revision), `longrun-021`, `verif-003`, `verif-005` |
| P6 | `README.md:30` | The README says `docket/budget.py` ends a run at 250,000 tokens. The file does not exist and `run.py` has no cap or budget; 12 runs used more than 250,000 tokens (all 12 ended `limit`), and no run ended for cost | judgment; `hooks-005`'s check "confirm the script path exists" is the same habit |
| P7 | `hooks/gate_release.py:15`, `hooks/gate_release.py:19` and `hooks/gate_release.py:21-24` | The gate fails open: a missing `precheck.py` returns 0, any exception (timeout included) returns 0, and so does any exit other than 2, a crash of the precheck among them. A release is refused only when the precheck runs and answers exactly 2 | `hooks-005`, `hooks-006`, `sdk-059` |
| P8 | `docket/run.py:129` | `"status": "ok"` is a literal. The README calls it the health of the run; it is `ok` in 55 of 55 rows, dead, limit and stalled runs included, and it is the only constant field in the ledger | judgment (the guide: a status that takes the same value on every run carries no information) |
| P9 | `docket/run.py:127` (the ledger row), `docket/precheck.py:14` and `docket/release.py:80` | The verdict is attached to the run and not to the pack that was reviewed. The row carries no digest of `work/<run>/pack` (0 of the 23 closed rows do); the precheck reads only `outcome`; `release.py` publishes whatever is in `work/<run>/pack` on the day it runs, and the workspace stays writable until its `freeze` step. A change after the closing round ships under a verdict that covered another artifact, and nothing in the records could show it. This is a gap in the code path, not something the counts reveal | judgment (the guide's "what a verdict is attached to"); `verif-012` is the rule-side analogue |
| P10 | `docket/run.py:79` and the verdicts | The runner cannot tell the reviewer's own failure from a failed criterion. A non-zero exit or a reply without a `VERDICT:` line becomes `fail`, and a reviewer that cannot do its job says so as a failed criterion. 2 of the 71 rejected rounds with verdict files say in their text that nothing could be judged (a timeout fetching the baseline, a lost working directory); each is recorded as `primary: fail` with criterion ids, and in both the run went on to another round with that text as the executor's feedback. There is no distinct state and no retry. These 2 are the environment rounds counted in P5(b) | judgment (the guide's handoffs paragraph: a gate that blocks on its own malfunction stops work for a reason unrelated to the work); `plat-052` is adjacent |

P5 and P1 are a pair that a review can easily merge. Score them separately: P1 is the
stop test in `run.py`, P5 is what the records say about what rejections buy. P4 and P9
are also a pair: P4 is the contract the executor can edit, P9 is the pack the verdict is
not tied to. P10 shares its two rounds with P5(b); score P10 only when the report names
the code path or says the reviewer's malfunction is recorded as a failed criterion.

Things in `process-planted` that are **not** defects, and count as false findings if
reported as problems:

- **The second reviewer, from another vendor** (`second` in the ledger). It ran 26
  times, only after the checks were green and the primary reviewer had passed, and it
  failed 3 of 26. In all 3 the checks were green and the primary had passed, and the
  next round passed in 3 of 3. It is paying for itself (`evals-012`, `longrun-001`).
  `verif-001` and `verif-028` argue against stacking a second model reviewer without
  evidence, and the guide asks for exactly that evidence: here the records supply it.
- **The release sequence** (`docket/release.py:72`): freeze, manifest, upload, verify,
  flip, prune, in that order and no other. Only one order is safe, and the README says
  why: the pointer flips only after the copy is verified, and the previous version is
  deleted only after the pointer has moved. The pointer is written to a temporary file and
  renamed over `mirror/current`, and an upload goes to a partial name that is renamed into
  place, so a crash leaves no empty pointer and no half copy under the run's name. Calling
  it rigid or ceremony is wrong. That the release writes no record of itself is true and
  minor.
- **The `refs` check.** It was red in 2 of 128 rounds. Both times the primary reviewer
  had passed the round (its text says every parent resolves) and the check output lists
  dangling parents; both next rounds passed. A cheap check that rarely fires and catches
  a failure that is costly downstream.
- **The round limit** (`docket/run.py:21`, `MAX_ROUNDS = 4`). It is explicit and right
  (`verif-003`, `verif-004`, `verif-034`). That 14 runs reached it is evidence for P5,
  not a second defect and not a reason to drop the limit.

Observations outside the key that are true of the setup and that a good review may add,
without their counting either way: `touched`, `tokens` and `seconds` are written and
read by nothing; verdict files exist for 35 of 55 runs only; the precheck tests only
the outcome (P9 is the consequence that matters); a round or two is rejected for form
alone; `schema` checks a type only when the key is present, so a record without `rank`
passes it; the reviewer's recall on a planted defect has never been measured.

### `process-clean`: one open finding, otherwise sound

51 runs, 48 verdict files (they cover 28 of the 51 runs, the later ones), 51 contract
files. Outcomes: 38 closed, 7 escalated, 2 limit, 2 stalled, 2 dead. The process is the
same one with these properties, each of which the README states and the code does. Most
were added after a blind review of an earlier version found the gap, so each is checked
here against the generated records and not only against the code.

- The contract is written read-only to `contracts/` outside the executor's workspace,
  its sha256 goes in the ledger, and the runner compares the file with it after every
  executor turn. All 51 contract files match their ledger hash. A mismatch ends the run
  `escalated` (exercised with a stub executor that edits the file). The runner seals
  `baselines/<run>/` and `checks/` the same way, by digest before the first turn and after
  each one (exercised with a stub executor that rewrites the baseline).
- Before any executor is paid, `lint` (`run.py:64`) refuses a contract whose criterion
  names an activity (`reasonable`, `carefully`) or a pack file the pack does not hold.
  3 of 51 runs ended `escalated` on it, with 0 rounds and 0 tokens, and they are exactly
  the 3 of 51 contracts that carry such a criterion. What a script cannot see still
  reaches the reviewer: the 7 escalations are 3 at the lint, 2 on `ESCALATE` (a criterion
  that contradicts the goal; 1 round each, 93,803 tokens in all) and 2 on `BLOCKED:`.
- The executor has a way to say it cannot do the work: `BLOCKED:` as the first line of
  `report.md` (`run.py:190`) ends the run `escalated`. 2 ended `escalated` on `BLOCKED:`,
  with 1 round, no check and no reviewer.
- The checks decide what a script can decide. `schema` (C1), `refs` (C3), `fields` (the
  ticket's field present and not a placeholder, C2), `scope` (against the input pack kept
  outside the workspace: ids unique, no record missing or added, no file added, nothing
  outside the scope changed, exercised with a stub that adds a record and one that adds a
  file; C4) and `accept` (the input's unit tests, kept in `baselines/<run>/tests`, plus any test
  file the executor added; a change to an input test file is reported and the input version
  runs, so an edit cannot turn C5 green, C5). All 51 contracts name these five.
  19 of 78 rounds add a test file (`tests/test_<field>.py`) and none edits an input test.
  25 of 78 rounds had a red check (`fields` 9, `scope` 12, `accept` 6; some rounds had
  two), and in none of them was the reviewer called. The reviewer was called in 51 rounds:
  38 PASS, 11 FAIL (all on C2, a judgment about values) and 2 ESCALATE.
- The reviewer reads a copy of `pack/` and `tests/` (`run.py:109`) that holds neither the
  executor's report nor its notes, and reads the files themselves, so nothing is cut at a
  length. The contract is in its prompt.
- The loop has exits that are not exhaustion, and its stop test compares what a round
  says with ids, numbers and quoted values blanked out (`run.py:138` and `run.py:147`),
  stopping only when the offenders did not fall: 2 stalled runs repeat a finding on as
  many records, and 1 run that repeated a finding on fewer records went on and closed. A
  token cap in `run.py` (the one run at or over 250,000 tokens ended `limit`) and a round
  limit of 3 back it. A reviewer that gives no verdict is asked once more and then ends the
  run as `error` without a word to the executor (no run in the records ended so).
- The ledger row of a closed run carries `pack_sha`, the digest of the pack the checks and
  the reviewer saw (38 of 38 closed runs). The precheck recomputes it from
  `work/<run>/pack` (`precheck.py:25`) and `release.py` does so again after the pack is
  frozen, so a change after the last review stops the release.
- The release is restartable: the pointer is written to a temporary file and renamed
  (`release.py:62`), an upload goes to a partial name, and a copy left by a release that
  never flipped is replaced on the next attempt (exercised on a scratch copy).
- Records have readers: `docket/stats.py` reads the ledger, the next round reads the last
  verdict file, the precheck reads the outcome, the contract hash and the pack digest. No
  ledger field is constant. Each round row carries `exec_tokens` and `review_tokens`, which
  add up to the run's `tokens` in 49 of 51 rows (the 2 dead runs have no round: their
  8,195 tokens are in the run total only); the executor spent 2,871,185 in rounds and the
  reviewer 617,266. A dead run's `reason` holds the executor's exit code and the end of its
  stderr, and a call that does not answer in time ends as a dead run, a red check or an `error`, not
  as a runner that stops without a row.
- The gate fails closed: a missing precheck, a crash, a timeout or any exit other than 0
  refuses the release (exercised: a run that had not closed was refused, and so was a run
  whose pack was edited after it closed).
- The round after a rejection passed in 24 of 32 cases, and every one of the 38 closed
  runs changed a pack file in its closing round. Of the 27 rejected rounds that have
  verdict files, 23 of the 27 rejected rounds put the defect in the work, 2 are the
  escalated contract defects and 2 are the executor's `BLOCKED:`. Runs that did not close
  used 730,918 of 3,496,646 tokens.

Residues: true of this process, and the cost of one that is sound. None is a defect;
the first three come from the second blind round, which presented them as significant.

- **Red checks.** 25 of 78 rounds ended on a red check. That is the check doing its job,
  before a reviewer is paid. The executor does not run the checks itself, which is a design
  option and not a defect: the check output is what goes back to it, and a closed run in 2
  rounds costs 37,766 tokens more than one in 1 (83,764 against 45,998, means over runs of
  different difficulty).
- **Missing data.** 7 runs had a red `fields` (6 of them closed), 657,106 tokens, 18.8% of
  the total. The `scope` check caught the one repair that deleted records (r20261114083758,
  18 input records missing) and the reviewer the one that copied values from neighbours
  (r20261109083903, which ended `limit`). The executor's prompt already offers `BLOCKED:`,
  and 2 runs used it. What is left is an executor that fills instead of stopping, which no
  script can decide.
- **A contradiction with the goal.** The 2 ESCALATE runs (93,803 tokens) each had C4 saying
  `pack/groups.json` is unchanged while the goal changes it. Only a reader sees that; the
  lint decides words and file names, and a rule written for these two would catch these two.
- **The reviewer is unmeasured, and its feedback is a count and a first id.** All 11 FAILs
  are on C2 behind a green `fields`; nobody has run the reviewer on planted defects or on
  known-clean work, and the guide says a process should have both. That needs a live model,
  not a change to this fixture. The executor gets "n records ...; the first is X" from both
  the checks and the reviewer: a full list would change every check's output, the stop test's
  count and the 48 verdict files, and the executor can find the offenders of a script check
  by scanning its own data. Costs more than a cheap fix, so it stays.
- **Records that were left out on purpose.** 30 of 78 rounds have no verdict file (the early
  runs, which the README says); nothing records whether a closed run was released or used.
- **A soft token cap.** The cap is tested after a round, so 1 run ended at 276,332 tokens
  against 250,000, and `limit` covers both that exit and the third round.
- **Smaller, true.** A contract defect or a blocked executor ended 7 of 51 runs;
  `baselines/` and `reviews/` grow without limit.

Open, found by the fourth blind round and not fixed in this revision of the fixture: some
tickets' C2 states something a script could decide (a file ordered by `rank`, unique skus, an
ISO date, a slug's form) and `fields` checks presence and placeholders only, so those go to
the reviewer. A report that names it has a true finding; do not count it as false, and do not
count its absence as a miss.

Found and fixed, each by a blind review of an earlier version: checks that missed defects
a script can decide; a stop test that compared text with ids and counts; an approval tied
to the contract and not to the pack; a pointer written in place; `accept` running the tests
from the executor's workspace, where the executor could edit them (2 of 6 red `accept`
rounds were followed by a round that touched a test file and went green; now `accept` runs
the input's tests); `scope` that did not see an added record or file; a baseline and
checks without the digest the contract has; tokens kept per run only and a dead run with no
reason, and a runner that a hung call would stop with no row. Review this version blind
again before trusting the residues list: it holds what three rounds found, not what a
fourth will.
