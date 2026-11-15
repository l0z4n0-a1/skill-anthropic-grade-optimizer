# Reviewing a whole setup

A setup is a system. Its pieces compete for the same context window, route work
to each other, and enforce or fail to enforce the same rules. Most of what makes a
setup weak lives between pieces, which is why this review looks at the whole
before any part. The five questions below go from the ones that usually change
the most to the ones that change the least. Take them in that order and spend
your effort where the measurement points; a setup rarely has serious problems
under all five.

Before each question, read the claims for it. The command is given with each;
start with `--brief` and expand what matters, as SKILL.md describes. Add
`--model <id>` to include what is specific to a model. A setup is usually read by
more than one: use the model that served most main-session requests in the
measurement for the instruction file and the skills, and each subagent's own
model for that subagent. When the configured model and the one that actually ran
differ, that difference is itself worth raising.

## 1. Is each thing in the right kind of piece?

`python scripts/kb.py show harness,hooks,settings`

Claude Code offers several places to put knowledge and rules, and they differ in
one way that decides most placement questions: whether what they hold is
guaranteed or merely likely. A hook or a permission rule runs as code, so what it
enforces always happens. An instruction in CLAUDE.md, a rule file, a skill or a
subagent prompt is text the model reads and weighs, so it is followed most of the
time and not all of it. Neither is better. Guarantees are rigid and cannot judge;
instructions adapt and can be missed.

So for each rule and each recurring procedure in the setup, ask what kind of
thing it is.

A rule that must hold every time, where one miss is costly (never push to main,
never write outside the project, always run the formatter), belongs in a hook or
a permission rule. Written as prose it will eventually be missed, and the usual
response, repeating it in capitals, makes the surrounding instructions worse
without making this one reliable. Read the hook claims before recommending one:
which exit code blocks, which events can block at all, and what happens when a
hook times out are easy to get wrong, and a hook that cannot fail is not a gate.
Check the setup's existing hooks against the same claims, using the hook
definitions in the measurement (event, matcher, timeout, options) and reading
the hook scripts themselves. Weigh each hook with the permission mode beside it:
the less the mode asks the person, the more a hook that fails open matters.

A step that needs no judgment and repeats (counting, renaming, converting,
collecting the same facts each session) belongs in a script the model calls, not
in instructions the model carries out by hand each time. The model doing by
reasoning what code does exactly is slower, costs tokens on every run, and
occasionally gets it wrong.

A fact or convention that matters in most sessions belongs in the instruction
file. One that matters only for some files belongs in a path-scoped rule. A
procedure or body of knowledge that matters for some tasks belongs in a skill,
where only its description costs context until it is needed. Work that is heavy
on reading and whose detail the main session does not need belongs in a
subagent, which spends its own context and returns a summary.

The findings here are mismatches: a guarantee written as prose, a judgment call
frozen into a hook, a once-a-month procedure sitting in the file every session
loads, a deterministic chore done by the model, a hook that exits with a code
that does not block.

## 2. What does every session pay, and what does it buy?

`python scripts/kb.py show context,cost`

The measurement gives the fixed cost of the person's own files at session start
(`fixed_context_est_tokens`) and, beside it, what was used in the window
(`skill_invocations`, `typed_commands`, `agent_spawns`,
`never_invoked_in_window`). Read them together. A piece that loads every session
and was never used in thirty days is paying rent for nothing, and the fix is
usually cheap: remove it, disable it, or stop the model from loading it on its
own so it costs nothing until someone types its name.

Treat "never invoked" as a question to raise with the person, not a verdict. The
window may miss seasonal work, and the count sees only this machine. For plugin
skills, the remedy is the plugin's own enable switch.

Then look past the fixed cost, because it is rarely the largest. The usage block
shows where tokens actually went: `avg_prompt_tokens_per_request` says how large
the working context runs in the main session and in subagents,
`tool_result_chars` says which tools fill it, and the split between main session
and subagents says who is doing the work. Set the average beside the compaction
window in the settings values: an average close to the window means sessions
spend most of their life near the ceiling. A setup whose requests average far above its fixed cost has a
conversation-growth problem, and trimming instruction files will not touch it;
the levers are clearing between tasks, sending bulky output to files, and moving
heavy reading into subagents. Say which lever fits the numbers you see. The cost
claims give Anthropic's order for the levers; follow it instead of leading with
whichever is most visible.

For MCP servers, the script knows only that they exist. Ask for `/context all`
when the setup has several, since their tool definitions can be a large part of
the window and only that command shows it.

## 3. Can the model find the right piece?

`python scripts/kb.py show skills,subagents --grep description`

Skills and subagents are chosen by the model from their descriptions. That makes
a description routing text, read alongside every other description, and it
succeeds when it lets the model tell this piece from its neighbours. The
measurement lists pairs whose descriptions share vocabulary
(`description_overlaps`). That list is a place to start reading, not a result:
shared words do not mean confusion, and two pieces with no words in common can
still claim the same request.

Read the descriptions as a set. For each, ask what request it should win and
whether another piece would also plausibly claim that request. Look for pieces
that say what they are but not when to use them, pieces whose boundary with a
sibling is stated in neither, descriptions cut off by the listing limit (the
measurement flags `listing_truncated`), and pieces that grew a list of trigger
phrases one missed request at a time. Where two pieces genuinely overlap, the
fix may be merging them, or giving each a sentence that names the other and says
which case goes where.

Usage is evidence here too. When a general-purpose agent is spawned far more
often than the specialised ones (`typed_agent_share_of_spawns`), either the
specialists' descriptions are not winning the work they were built for, or the
roster has a gap where the general agent is filling in. Which one it is takes
reading the agent definitions. Remember that spawn counts cover every project on
the machine and that the setup may have changed inside the window, so a pattern
that predates a recent change is a reason to measure again later, not a finding.

## 4. Is each role on the right model and effort?

`python scripts/kb.py show model --model <id>` and `python scripts/kb.py model <id>`

The measurement shows the model and effort each subagent declares and, in
`requests_by_model_and_effort` and `tokens_by_scope_and_model`, what actually
ran. Compare the two with the claims on what each model is recommended for and
how its effort levels behave. Effort names do not mean the same thing from one
model to the next, and defaults differ between models and between the API and
Claude Code, so an agent that leaves effort unset is making a choice the person
may not know about.

Look for roles whose work does not match their tier in either direction:
mechanical work on the most capable model, or work that needs judgment on the
smallest one. Look for agents with no model set, which run on whatever the main
session uses and so change tier whenever the person switches model. And where
the setup spreads work across several models to save money, weigh that against
what the claims say about running one capable model at lower effort, since a
cascade gives up cache reuse between models.

Recommend a change of model or effort as something to try and measure, with the
quality check that would show it held. These are the recommendations most likely
to be wrong for a particular workload, and the person's own results outrank the
general guidance.

## 5. Is each piece well made for what it does?

Now read individual pieces, using `references/piece-review.md`. Do not read all
of them. Choose by leverage: the instruction file every session loads, the
skills and agents the usage block shows carrying the most work, and anything the
earlier questions flagged. A flaw in an agent that ran three hundred times
matters more than a flaw in one that ran twice.

For instruction text that may simply be dated, written for an older model or
contradicted by the repository, recommend `/doctor prompt-audit`, which is built
for exactly that and reads every file. Spend your own reading on what it does
not judge: whether the piece is good at its job.

## Reporting

Lead with what you found, in two or three sentences a person could act on
without reading further: the largest problems and roughly what fixing them is
worth. Then the measured picture in a few lines, then the findings in order of
effect, each in the shape SKILL.md describes. Close with what you did not look
at and what the measurement could not see, so the person knows the edges of the
review.

Suggest keeping the measurement JSON. After changes, a second run with
`--compare` shows what moved, and usage figures are comparable once enough
sessions have passed that the two windows do not overlap.
