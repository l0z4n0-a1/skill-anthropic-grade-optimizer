# Reviewing a whole setup

A setup is a system. Its pieces compete for the same context window, route work
to each other, and enforce or fail to enforce the same rules. Most of what makes
a setup weak lives between pieces, which is why this review looks at the whole
before any part.

## How to think while doing it

These habits separate a review that finds the cause from one that lists
symptoms.

**Work out what the setup is for before judging it.** The usage block shows
which skills and agents carry the work and which models serve it. A setup built
for one person's research is judged differently from one shared by a team that
ships code, and the same piece can be dead weight in one and essential in the
other.

**Follow one important rule end to end.** Pick the rule whose failure would
cost the most and trace it: where is it written, what enforces it, and does that
enforcement actually stop the action? Defects that look small in isolation
often combine. A rule stated only in prose and a hook that reports an error
without blocking are two minor findings separately and one serious finding
together, because between them the rule is enforced nowhere.

**Look for the cause behind several symptoms.** When three things look wrong,
ask whether one thing produces all three. Reporting the cause once is worth more
than reporting its effects three times, and it points at the change that fixes
them together.

**Try to break your explanation before reporting it.** When you form a
hypothesis about why a number looks the way it does, ask what you would see if
it were false, and go look when the evidence is at hand: the settings values and
the usage figures are already in the measurement. Report an explanation as
confirmed only if you checked it, and as a hypothesis otherwise.

**Ask what would change if the piece were gone.** If the honest answer is
nothing, the piece is cost. If you cannot tell, that is a question for the
person, not a finding.

**Price each recommendation.** Every change gives something up: a hook that
blocks when it fails also stops work when it fails; a skill removed for disuse
is missing the one time it was needed. State the cost with the change, so the
person is choosing and not just obeying.

**Mind the window.** The measurement covers thirty days in which the setup
itself may have changed. A pattern from before a recent change is a reason to
measure again later.

## The six questions

They go from the ones that usually change the most to the ones that change the
least. Spend effort where the measurement points; a setup rarely has serious
problems under all six. Before each, read its core claims with the command
given. A setup is usually read by more than one model: use the one that served
most main-session requests for the instruction file and the skills, and each
subagent's own model for that subagent. When the configured model and the one
that actually ran differ, raise it.

### 1. Is each thing in the right kind of piece?

`kb.py core placement`, then `kb.py core hooks` if the setup has hooks or needs one.

The places Claude Code offers differ in one way that decides most placement
questions: whether what they hold is guaranteed or merely likely. A hook or a
permission rule runs as code, so what it enforces always happens. An instruction
in an instruction file, a skill or a subagent prompt is text the model reads and
weighs, so it is followed most of the time. Neither is better. Guarantees are
rigid and cannot judge; instructions adapt and can be missed.

So for each rule and each recurring procedure, ask what kind of thing it is. A
rule that must hold every time, where one miss is costly, belongs in a hook or a
permission rule; written as prose it will eventually be missed, and repeating it
in capitals degrades the surrounding instructions without making this one
reliable. A step that needs no judgment and repeats belongs in a script the
model calls. A fact that matters in most sessions belongs in the instruction
file; one that matters only for some files, in a path-scoped rule; a procedure
that matters for some tasks, in a skill; work that is heavy on reading and whose
detail the main session does not need, in a subagent.

Check existing hooks against the hook claims, using the definitions in the
measurement (event, matcher, timeout, options) and reading the hook scripts.
Which exit code blocks, which events can block at all, and what happens when a
hook fails or times out are easy to get wrong, and a hook that cannot fail is
not a gate. Weigh each hook with the permission mode beside it: the less the
mode asks the person, the more a hook that fails open matters.

### 2. Can the model check its own work?

`kb.py core feedback`

A model stops when the work looks done. Whether it is done depends on a check
the model can run and read: a test suite, a type checker, a linter, a build, a
script that compares output with an expectation. A setup that gives the model
such a check and says exactly how to run it gets work that was verified; one
that does not gets work that was declared finished. This is cheap to add and
changes results more than most instruction text does.

Look for the check and for how strictly it is applied. Does the instruction
file name the exact commands, including how to run one test and not the whole
suite? Is completion left to a request in the prompt, or does something enforce
it: a hook that runs when the model stops, a reviewer in a fresh context? Do
subagents that produce work say how that work is confirmed, and do they report
what they verified apart from what they assumed? For work that runs unattended,
the bar is higher, since nobody is watching.

The finding here is usually an absence, so say what is missing and write the
line or the hook that would supply it, using what the project already has. If
the project has no automated check at all, that is the finding, and no
instruction text substitutes for it.

### 3. What does every session pay, and what does it buy?

`kb.py core economy`

Read the fixed cost of the person's own files (`fixed_context_est_tokens`)
beside what was used (`skill_invocations`, `typed_commands`, `agent_spawns`,
`never_invoked_in_window`). A piece that loads every session and was never used
is a candidate to remove, disable, or make invocable by name only, so it costs
nothing until someone asks for it. Treat "never invoked" as a question for the
person: the window may miss seasonal work and sees only this machine.

Then look past the fixed cost, because it is rarely the largest.
`avg_prompt_tokens_per_request` says how large the working context runs,
`tool_result_chars` says which tools fill it, and the main and subagent split
says who does the work. Set the average beside the compaction window in the
settings values: an average close to the window means sessions spend most of
their life near the ceiling. When requests average far above the fixed cost, the
problem is conversation growth and trimming instruction files will not touch it.
The core claims give Anthropic's order for the cost levers; follow it instead of
leading with whichever is most visible.

`cache_rebuilds` counts the times a session paid again for context it already
held, and says why where the history shows it: the person paused longer than
the cache lives, or switched model mid-session. Each one rewrites the whole
working context at the cache-write price, so a large session resumed after a
long pause is among the most expensive single requests there is. When pauses
dominate, the remedy is a habit: clear or compact before stepping away, or
start fresh on return. When model switches dominate, it is choosing the model
before the session grows. The count is a floor: it sees main sessions only and
cannot tell compaction from a tool or settings change.

For MCP servers the script knows only that they exist. Ask for `/context` output
when the setup has several.

### 4. Can the model find the right piece?

`kb.py core routing`

Skills and subagents are chosen from their descriptions, read alongside every
other description. One succeeds when it lets the model tell this piece from its
neighbours. `description_overlaps` lists pairs that share vocabulary; it is a
place to start reading, since shared words do not prove confusion and two pieces
with no words in common can still claim the same request.

Read the descriptions as a set. For each, ask what request it should win and
whether another piece would also claim it. Look for pieces that say what they
are but not when to use them, pieces whose boundary with a sibling is stated in
neither, descriptions cut by the listing limit (`listing_truncated`), and lists
of trigger phrases grown one missed request at a time. Usage is evidence too:
when one of two similar pieces takes all the invocations, the other is either
redundant or losing requests it was built for.

### 5. Is each role on the right model and effort?

`kb.py core allocation`, then `kb.py model <id> --brief` for each model in use.

Compare what each subagent declares with what ran. `agent_runs` gives, for each
agent type, how many times it ran, on which models, and what one run costs in
requests and tokens; `requests_by_model_and_effort` and
`tokens_by_scope_and_model` give the totals. An agent that names no model shows
up under several, because it follows whatever the session was on. Effort names do
not mean the same thing from one model to the next and defaults differ, so an
agent that leaves effort unset, or a model unset, is making a choice the person
may not know about. Look for roles whose work does not match their tier in
either direction.

Anthropic's documentation says how model and effort are chosen and inherited,
and what each current model is recommended for. It does not give a general rule
for matching a tier to a kind of work, so a recommendation here is your
judgment: label it so. The person's own numbers are better evidence than any
general ranking, because they measure this work. Frame a change as an
experiment: move one role to another tier or effort, keep the quality check
that would show whether the output held, and compare that role's cost per run
in `agent_runs` once enough runs have accumulated. Public benchmarks rank models
on tasks that are not the person's, so leave them out of the basis for a
finding.

### 6. Is each piece well made for what it does?

Read individual pieces with `references/piece-review.md`, chosen by leverage:
the instruction file every session loads, the skills and agents that carry the
most work, and anything the earlier questions flagged. For text that may simply
be dated, recommend `/doctor prompt-audit`, and spend your own reading on
whether the piece is good at its job.

## Reporting

Lead with what you found, in two or three sentences a person could act on
without reading further. Then the measured picture in a few lines, then the
findings in order of effect, in the shape SKILL.md describes. Say what you chose
not to change and why, since a review that names what is sound is easier to
trust. Close with what you did not look at and what the measurement could not
see.

Suggest keeping the measurement JSON. After changes, a second run with
`--compare` shows what moved; usage figures are comparable once the two windows
no longer overlap. `kb.py core verifying` holds what the documentation says
about telling whether a change helped. It covers evaluations in general and
does not describe measuring a whole setup, so present before-and-after
measurement as this skill's method.
