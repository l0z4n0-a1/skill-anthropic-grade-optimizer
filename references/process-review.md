# Reviewing an orchestration process

Some setups contain a system of their own: a runner, a workflow or a set of
conventions that hands work from one session to another. One session writes a
plan or a contract, another executes it, a third reviews, a loop sends rejected
work back, and records are kept along the way. This review asks what each
stage buys, and it answers from what the process has actually produced before
it answers from its design.

## Start from what one session would do

State in one sentence what the process is for, and then the comparison it has
to beat: a single session with the same tools and a clear request. Name first
what the process must guarantee whoever does the work: who may approve, what
must stay isolated from what, what has to be on record. The comparison is the
simplest design that still meets those, and a stage that exists to keep
approval apart from authorship is not a workaround for a weak model. A stage
earns its place by buying something you can name: a context kept clean of
another stage's reasoning, work that runs in parallel, a tool set or domain
focus one agent could not hold, a judgment that does not inherit the author's
blind spots, or a check that a script can make and a model cannot fake. A
role, a persona or a long prompt is not one of those. What a stage costs is
usually tokens and a boundary where context is dropped; check both, and look
hardest at a boundary drawn between two stages that need the same context.
`kb.py core process` is the first read; add `kb.py core verifying` for any
process with a reviewer and `kb.py core subagent` for how it delegates. Few
claims speak about loops, gates and records directly; where they are silent,
`references/foundations.md` gives the principles this guide's questions come
from, and a finding built on one says so.

## Count what the runs show, and know what they cannot show

Before opening the records, read the process's own description of itself and
write down, in a few lines, what that design leads you to expect: where runs
will end, what the reviewer will mostly reject, which stage will turn out to do
nothing. `references/foundations.md` is the source of such predictions. Keep
the lines. A count that matches a prediction confirms little; a count that
contradicts one is where the report should spend its attention, and without
the written prediction you will not notice that you were surprised.

Then find what the process leaves behind (a ledger, receipts, verdict files,
logs, session transcripts) and count:

- How runs end: closed, stopped at a limit, escalated to a person, or dead
  before any review happened. What each group cost.
- Next-round pass rate: of the rounds that were rejected and followed by
  another round, how many then passed. Report beside it the rounds a run took
  to be accepted and the share of runs never accepted, since a process that
  abandons its hardest work improves the first number.
- What later rejections are about. Read the verdicts of consecutive rounds and
  sort each later rejection: the same finding again, a new finding in what the
  executor just changed, a finding in material the round did not touch, or a
  criterion that could not be met or checked as written. Verdict text and a
  list of touched files often cannot place a rejection; count those as
  unknown, and do not infer what a repair introduced without the two versions
  of the work.
- Closed runs that closed because the work changed, against those that closed
  because the contract or the check was edited and the review re-run.
- Checks that were green while a reviewer still found a defect, and checks
  that were red on finished work.

Report counts with their base and the window they cover: which runs have
records, from when, and whether the model, the contract format or what is
retained changed inside that window. Say what the counts rest on: a count is
as good as the records, and a self-written summary of a run is not a verdict.
A count
built on a reviewer's verdicts (who was at fault, which criteria failed, how
many defects) inherits that reviewer's errors. If nobody has measured the
reviewer on planted defects and on clean work, say so next to every number
that rests on it.

Ask the person one thing before the counts harden into a reading: of the runs
that did not close, which did they use anyway, which did they redo by hand,
and why. Unclosed runs whose work was used suggest the reviewer or the
contract was the obstacle; unclosed runs that were redone suggest the work
was. Neither settles it: a person can knowingly accept a defect, or redo
sound work because the requirement moved, which is why the reason matters.
The records cannot tell these apart. If the person is not there to ask,
report both readings.

Records show what the stages caught and what they cost. They do not show what
the process added over a single session; only running the same task both ways
shows that. So a ledger can tell you a reviewer found real defects and still
not tell you the process is worth its cost. Where there are no retained
records, compare what went in with what was delivered for a few recent tasks,
and ask the person; say that the review had no run history to count.

## From a symptom to its cause

A count is a symptom, and most symptoms have more than one cause with a
different remedy each. Do not name a cause until a second count has separated
it from its rivals. The common ones:

| The records show | It could be | What separates them |
|---|---|---|
| The round after a rejection rarely passes | criteria that cannot be met as written; a reviewer raising old material each round; an executor not told enough to repair; each repair exposing the next defect | sort the later rejections as above: criterion, untouched material, repeated, new in what changed |
| Checks green, reviewer rejects | checks miss what a script could decide; the criterion needs judgment; the reviewer is noisy | read what the rejections name: is it mechanically checkable? what does the reviewer do with known-clean work? |
| A stage almost never rejects | it cannot fail; it does not discriminate; the work reaching it is good | read its exit paths and follow by hand what a defective input would meet; look at what the stage before it removes; propose a planted-defect run to the owner |
| A stage rejects most of what it sees | it is rigorous on poor work; its criteria are unmeetable; it is noisy | what happens next: repaired work, an edited criterion, or the same finding again |
| Runs end at the cap | the task is larger than the cap; the loop is not converging; the stop test cannot see repetition | compare consecutive verdicts in capped runs: same class of defect or different |
| Runs are stopped early for no progress | the work had stopped moving; the stop test took movement for repetition | read the last two verdicts of every run stopped this way: the same defect, or one repaired and another exposed |
| Runs close after an edit to the criteria | a sound correction by the criteria's owner; the judged party moving its own target | who made the edit, and whether the work also changed in that round |
| Many runs die before any review | environment faults; a start-up cost the task does not survive; the runner's own defects | where in the log they die, and whether the same run restarted succeeds |
| A recorded field never varies, or nothing reads it | it was meant for a reader that was never built; it is a constant by mistake | search the code for a reader; count distinct values |

When the records cannot separate the rivals, say which count is missing and
what would have to be kept for the next review to make it. That the process
does not keep what its own diagnosis needs is itself a finding.

Report the predictions you wrote and which of them the counts overturned.
Predictions are there to expose what you assumed; they do not rank the
report. Order findings by what each costs and how well it is shown, so a
severe defect you predicted correctly still comes first.

This review reads; it does not run the process or anything in it. Where a
question needs a test (a planted defect, a clean artifact through the
reviewer, the same task with a stage removed), trace the code path as far as
reading allows and propose the test as a change, for the owner to run where
it is safe.

## What to look at, in order

**The definition of done.** Is each acceptance criterion a state someone could
observe, or an activity? Then find which copy of the criteria and checks
actually judges the work. The executor may be able to edit a copy; what
matters is whether the judging stage reads one the executor cannot change, or
detects the change.

**The checks.** For each one: can it fail, and can it pass? A command that
exits zero whether or not the work was done is not a check, and neither is one
that cannot run where the reviewer runs. Prefer a deterministic check wherever
the criterion allows one, and keep model judgment for what a command cannot
see. Look for regions a check exempts, since those are where defects collect.

**The reviewer.** What does it see: the work and the criteria, or also the
executor's account of the work? Is each verdict tied to a criterion, or does
the reviewer add demands of its own? This guide's test of whether to trust it
is two measurements on work whose state is known independently: whether it
catches a defect planted on purpose, and what it does with work known to be
clean. The claims support the second directly (`verif-005`); taking the two
together as the bar is this guide's method. Without them, say that the
reviewer's reliability is unknown, not that it is poor. A loop with a noisy
reviewer does not only waste rounds: an agent executor tends to act on what
it is told, so look in the records for good work changed to satisfy a false
finding. A second reviewer stacked on a first is justified by the confirmed
defects it adds, net of the false alarms it adds (`verif-001` gives the case
against stacking without that evidence). The records often hold the evidence
already: look at the rounds it rejected after the checks were green and the
first reviewer had passed, and at whether the next round repaired the work.
When they show that, it is paying for itself and is not a finding.

**What a verdict is attached to.** Trace the thing that was approved to the
thing that was shipped. If the executor can change the work after the last
review and the runner acts on the earlier verdict, the approval covers an
artifact that no longer exists. Look for a revision or digest carried from the
verdict to the final action.

**The loop.** What does a new round receive that the last one lacked? How does
the loop decide it has stopped making progress? A comparison of which criteria
failed cannot tell a round that fixed nothing from one that fixed the first
defect and exposed a second. A loop needs a cap and an exit that is not
exhaustion (`verif-004`, `coord-025` for generator and verifier loops). That a
failure should go back to the stage able to repair it is this guide's
recommendation: a criterion that does not apply to the deliverable is not
something the executor can repair (`plat-052` describes the case), so look
for who may clarify a criterion, who may change it, and how the executor says
it cannot proceed.

**The handoffs.** At each boundary, what does the receiving stage know when it
starts, and what does it send back? For a stage that starts cold, the claims
on briefing a subagent apply. Then ask how each boundary fails: a missing
script, an exception or a timeout that lets the work through in silence turns
a gate into a formality, and a gate that blocks on its own malfunction stops
work for a reason unrelated to the work. A reviewer is a boundary too: see
whether the runner can tell a reviewer that could not do its job (a timeout,
a reply with no verdict) from one that rejected the work, and search the
verdict texts for rounds where nothing was judged and a failure was recorded.

**Side effects and state.** Where a run acts on the world (posts, sends,
merges, pays) and also records that it did, walk the crash between the two. A
record written before the action is confirmed can skip work forever; an action
confirmed and not recorded is repeated on retry. Confirmation, state update
and recovery are one path and should be read as one.

**Records and what reads them.** For every file the process writes, find its
reader. A lesson recorded at the end of a run and never read by the next one
changes nothing. A status that takes the same value on every run carries no
information. A rate the instructions say decides something should be computed
somewhere, from records that are actually filled in. Before calling any of
these a defect, rule out the innocent readings: the reader may be a person
and not code, so ask; a value may be constant in the sample because the rare
case has not happened, so read whether the code can write another; records
may be missing because retention is limited on purpose. The finding is a
decision or a recovery step the process promises that depends on evidence it
does not keep.

**What the documents promise.** `references/setup-review.md` covers checking
a documented mechanism against the files. For a process, pick the one or two
guarantees its users rely on most (work is never accepted without review; a
run cannot exceed its budget) and test each end to end: find the code path
that would break the guarantee and see what stops it. Follow every route to
the final action, not only the usual one: a retry, a resume after a crash and
a manual re-run are where a check that guards the main path is missing.

**Fit to the current model.** Every stage encodes an assumption about what the
model cannot do alone. A stage nobody has re-examined since the model changed
is a finding in its own right: an untested assumption. That it should be
removed is a further claim, and it needs the same tasks scored with the stage
and without it; a handful of runs can suggest the answer and rarely settles
it. Keep the two apart in the report. This applies to stages that make up for
capability. A boundary of authority, isolation or permission is not an
assumption about the model; the question for it is whether it is still
enforced.

## Judging substance

Counts say where to look; they do not say whether the output was good. Take a
few runs the process closed and a few it did not, and read what was actually
delivered. Ask of the closed ones whether the person would have accepted the
executor's first output, and of the unclosed ones whether the work was in fact
wrong or only failed to satisfy the contract. The person can answer what the
records cannot: which runs they used as delivered and which they redid by hand.

## What not to flag

A cheap check that rarely fires and catches an expensive failure when it does
is doing its job; before calling any gate noisy or idle, look at how often the
failure it guards against occurs and how often it blocks clean work. A high
rejection rate is not a defect when the rounds that follow repair the work,
the loop is capped, and the repairs are not good work bent to satisfy the
reviewer. A reviewer on a different model or from a different vendor is a
design choice whose value the records can confirm or deny; this guide's
reading is that it is worth keeping when it finds real defects behind green
checks and a first reviewer's pass, and that is judgment, not documented
guidance. Ceremony is the stage
whose removal would change nothing; say that of a stage only when the records
or a removal test show it.

Keep a defect apart from a cost. A round that went red because a check caught
what it exists to catch is the check working, and a contradiction that only a
reader can see will reach a reader. These are true, they have a count, and the
owner would not fix them; report them as costs, with the count, and not as
findings. The test for a finding is that the owner, shown the evidence, would
change the process. One exception: a guarantee the process states and the
code does not keep is a finding even when the owner accepts the risk. Report
it, and report that they accept it.

## Proposing changes

Propose the smallest removal or rewiring that the evidence supports, one at a
time, each as an experiment: which count should move, over how many runs, and
what result would mean the stage should come back. Give the concrete edit.
Leave the redesign to the author, who made decisions the records do not show.
