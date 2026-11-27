# Foundations: the older principles under the claims

The knowledge base records what Anthropic's documentation says, and it ages
with the product. Under much of it are principles from measurement, control,
information and systems design that were true before language models and will
outlast any release. This file names the few that change a review verdict.

They are here for two uses. When a setup does something no claim covers, a
principle lets you reason about it instead of guessing. And when a claim's
source changes or disappears, the principle says whether the advice was a
fact about one release or a consequence of something permanent.

They are not Anthropic's guidance, and a report must not present them as such.
A finding that rests on one gives its basis as `principle: <name>`, next to
any claim ids. Each entry has three parts kept apart on purpose: what the
original says, what this file takes from it for agent systems, and where to
look. The second part is this file's reading and not the author's. A claim id
after an entry marks guidance that points the same way; it does not mean the
claim states the principle.

What an entry tells you to look for is a question, and the answer has three
outcomes: the records contradict it, the records show it, or the records
could not have shown it either way. A ledger written only when a run succeeds
cannot contradict a prediction about crashes. Before treating silence as
absence, name the record that would have captured a counterexample and check
that it exists and is complete.

## Measurement

**An indicator used to decide outcomes comes under pressure that changes what
it indicates.** Goodhart observed that a statistical regularity tends to
break down once it is used for control; Campbell, that the more a
quantitative indicator is used for decisions, the more it is subject to
corruption and distorts the process it monitors. The short form, "a measure
that becomes a target ceases to be a good measure", is Strathern's. *Taken
here:* an executor that is told to make a check pass, and can reach the
check, its inputs or its criteria, has a route to passing that does not go
through the work. That the route exists is a design defect. That it was taken
is a separate finding and needs the history: what changed in the round that
closed, and whether it was the work. `verif-012` is the same rule from the
guidance side.

**A detector is described by two rates, and what an alarm means depends on a
third number.** Signal detection theory (Green and Swets) separates how often
a detector fires on a real signal from how often it fires on noise; neither
can be read from how often it fires. By Bayes' rule, most alarms are false
when the false-alarm rate times the share of clean inputs exceeds the hit
rate times the share of defective ones. *Taken here:* a reviewer has a hit
rate on real defects and a false-alarm rate on clean work, and its rejection
rate says nothing about either. A reviewer nobody has measured is of unknown
reliability, which limits what any count built on its verdicts can support;
it is not thereby a bad reviewer. `verif-005` describes measuring the
false-alarm side.

**Judges whose errors are correlated add less than their number suggests.**
Condorcet's jury theorem shows that a majority of independent, better than
chance voters is more reliable than one; the independence is what the result
rests on, and ensemble methods meet the same limit. *Taken here:* a second
reviewer earns its cost by the confirmed defects it adds, net of the false
alarms it adds. Shared training, shared context, or reading the author's
account of the work are reasons to expect its errors to track the first
reviewer's, and so to expect little; they are reasons to measure, not a
result. Two correlated reviewers can still catch different things. Compare
both on the same work.

**A message that could only have been one thing carries no information.**
Shannon's measure is zero for a source with one possible output. It is a
statement about what could be sent, not about what happened to be. *Taken
here:* a status the code can only ever write as `ok`, or a check with no
reachable failing exit, tells its reader nothing. A field that is constant in
the records is a reason to read the code that writes it; the rare value may
simply not have occurred, or only successful runs may write rows.

## Control

**A controller cannot respond differently to states it cannot tell apart.**
This is the observability idea from control theory, used here as a heuristic.
It is not a requirement that feedback be detailed: a loop can improve by
trial against a pass or fail signal and stop on success. *Taken here:* ask
whether two histories that call for different next actions look the same to
the loop. A round that repaired one defect and exposed another calls for
another round; a round that changed nothing calls for a stop. A stop test
that sees only which criteria failed cannot separate them. Test the question
on real consecutive rounds. `verif-003` and `verif-004` describe loops that
did not converge and what was changed.

**Access is granted on explicit permission, and the default is refusal.**
Saltzer and Schroeder's fail-safe defaults (they credit E. Glaser) is a
principle about authorization: a mechanism that fails should fail to "no
access". *Taken here:* for a gate that guards a protected action, an error
path that ends in the action going ahead is a defect. For an advisory check
on quality, blocking on its own malfunction stops work for a reason unrelated
to the work, so the error policy is a choice the owner should have made and
written down. In both cases follow a failure to the final decision before
reporting what it lets through: in Claude Code a hook that fails or times out
usually hands the call to the normal permission flow, which may still refuse
it (`hooks-005`, `hooks-006`).

**Every access to a protected object is checked.** Saltzer and Schroeder's
complete mediation. *Taken here:* find every route to the final action, not
only the usual one. A release that verifies its approval on the main path can
have a retry, a resume after a crash or a manual re-run that reaches the same
action without the check. One unchecked route changes the verdict even when
every recorded release went through the checked one.

**Some properties can only be established where the whole exchange is
visible.** The end-to-end argument (Saltzer, Reed and Clark) says a function
whose correctness depends on knowledge held at the endpoints cannot be
completely provided by a stage in between. *Taken here:* a review in the
middle of a pipeline establishes something about the artifact it saw. Whether
that holds for what ships depends on something carried to the end, such as a
digest of the reviewed artifact checked at the final action. Look for what
binds the verdict to the bytes.

**An effect and its record commit together, or the recovery path has to deal
with not knowing.** Inside one transaction the two are atomic. An effect
outside it (a post, a payment, a message to another system) leaves a window:
the process can die after acting and before recording, or lose the
acknowledgement. Delivery guarantees name the options: repeat until
acknowledged and risk a duplicate, or never repeat and risk an omission.
*Taken here:* find the transaction boundary. For each effect outside it, find
what the receiver does with a repeated request, for how long, and how the
process resolves an outcome it does not know. Expect duplicates or omissions
only where that recovery path allows them.

## Systems

**Working complex systems are usually found to have grown from simpler
working ones.** Gall's observation, from *Systemantics*; an aphorism, not a
law. *Taken here:* it is the reason a process review starts from what one
session would do. It does not make a system suspect for having been designed
whole. For each stage the question is the same whenever it was added: what
evidence is there of what it contributes. `longrun-071` describes scoring a
change before and after.

**Do not remove a fence until you know why it was put there.** Chesterton.
Ablation, testing a system with a part removed, is a separate method from a
different tradition and answers a different question. *Taken here:* a stage
may record a failure its author saw and the records no longer show, so read
the incident, the decision or the test behind it and ask the owner before
proposing a cut. Where the purpose may have expired with an older model, the
case for removal is the same tasks scored with and without the stage.
`longrun-013` is the guidance on re-examining a harness when the model
changes.

**General methods that scale with computation have overtaken methods built on
human knowledge of the domain.** Sutton's bitter lesson is about research
methods in AI. *Taken here, and this step is this file's and not his:*
scaffolding that spells out steps, splits work into narrow roles or re-checks
what the model now gets right may cost tokens, or hold work below what the
current model does unaided. It is a possibility to test with and without the
component, never a verdict from reading. Verification, isolation and
permission boundaries are not compensation for a weak model and do not expire
with one.

## Using them

Reach for a principle when it tells you where to look for something you can
then count or trace. Name it in the finding only if the finding would be
weaker without it. A report that quotes six laws and counts nothing has the
form of rigor and none of its content, which is the failure this skill exists
to find in others.
