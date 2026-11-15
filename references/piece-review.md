# Reviewing one piece

A piece can be valid and still be poor at its job. The frontmatter parses, the
file loads, nothing errors, and the skill never triggers or the subagent returns
work the main session has to redo. This review asks whether the piece is good
for what it is meant to do, which is a question about its purpose first and its
text second.

## Start from the purpose

Before reading for flaws, state in one sentence what the piece is for and who or
what reads it. Take it from the piece and from how it is used: the measurement
shows how often it was invoked, the model and effort it declares, and what else
in the setup sits near it.
If you cannot state the purpose after reading the piece, that is the first
finding, and probably the most important one, because a model reading it will
not be able to either.

Then read the claims for the kind of piece, with the model that reads it:

| Piece | Command |
|---|---|
| Skill, command, output style | `python scripts/kb.py show skills,prompting --model <id>` |
| Subagent | `python scripts/kb.py show subagents,orchestration,prompting --model <id>` |
| CLAUDE.md, rule file | `python scripts/kb.py show harness,context,prompting --model <id>` |
| Hook, permission rule, settings | `python scripts/kb.py show hooks,settings` |
| MCP server, tool definition | `python scripts/kb.py show mcp,tools` |
| Plugin | `python scripts/kb.py show plugins,skills` |

The reader's model matters. A subagent that pins a model is read by that model;
one that does not is read by whatever the main session runs. Instructions that
suit one model can be wrong for another, so a piece is always reviewed for a
particular reader.

## What to look at, in order

**The configuration, against the documented fields.** Claude Code ignores a
frontmatter field it does not recognise and says nothing, so a misspelled or
invented field is a setting the author believes is active and is not. Compare
every field with the claims. Check too what each real field does, since several
do less or other than their names suggest, and what the piece gets by leaving a
field out: a default is still a choice, and for tools, model and effort the
default may be far from what the author intended.

**The description, as routing text.** Whoever picks this piece reads only its
description, among all the others. Ask what request it should win, whether the
description would win it, and whether it would also win requests it should lose.
A good description says what the piece does and when to use it, in the words a
request would use, and where a sibling is close, says which case goes where.
Routing text may be more insistent than body text, because under-triggering is
the common failure; that is a difference of function, so do not flag firmness in
a description the way you would in a body.

**What the reader knows when it starts.** This decides most of whether the body
works. A skill's body arrives in a conversation that already has context. A
subagent starts with almost none of it: it has its own prompt and the message
that delegated the work, and it has not seen the conversation, the files already
read, or the person's preferences. So a subagent's prompt has to carry what a
capable newcomer would need to do this job well: what the work is for, what
good output looks like, where the hard parts are, what it may and may not touch,
and what to send back. Check each of those. Then check the other side: the
subagent's return is the only thing the main session sees, so the prompt should
say what shape the result takes and that it should separate what was verified
from what was inferred.

**Whether the instructions are designed for the job.** Read the body as its
reader would and ask where it would go wrong.

- Does it spend its words on what is hard about this task, or on what any
  capable model would do anyway? Generic virtues and restated defaults add
  length and no guidance, while the judgment calls that make the task difficult
  often get a line or nothing.
- Does it explain why? A rule with its reason lets the reader handle the case
  the rule did not foresee. A bare rule gets applied rigidly where it does not
  fit.
- Is its strictness matched to the work? Exact steps are right where only one
  sequence is safe. For work that needs judgment, a script of steps overrides a
  plan the model would have made better, and the claims say current models are
  hurt by it.
- Does it describe the situation or only issue orders? A description of who the
  output is for and what they need lets the reader infer many behaviors at once.
- Are its examples doing what the author thinks? Models imitate examples closely,
  so one example becomes a template.
- Does everything in it still fit the current reader? For text that looks
  written for an older model, the documented patterns are in
  `python scripts/kb.py show prompting`, and `/doctor prompt-audit` checks them
  file by file.

**Structure, for how the piece is loaded.** What sits at the top matters more
than what sits at the bottom, for reasons the claims make specific (what is kept
after compaction, what is truncated). Material needed only sometimes belongs in
a file the piece points to, with a line saying when to read it. A deterministic
step inside the piece belongs in a bundled script.

**Fit with the rest of the setup.** Does it repeat or contradict the instruction
file? Does another piece do the same job? Does it depend on a tool, path, command
or sibling piece that exists? The measurement and a few file checks answer these.

## Judging substance

The hardest part of this review, and the part no checklist reaches, is whether
the piece would produce good work. Two things help.

Imagine handing the piece, exactly as written and with nothing else, to a capable
contractor who has never seen this project. Where would they have to guess? Each
guess is a place the model will fill with a generic default.

And where the piece has run, look at what it produced. The person can tell you
whether its output is usually used as it comes or usually redone, and the
measurement shows whether it is used at all. A piece that is well written by
every standard here and whose output is routinely discarded has a purpose
problem, and rewriting its sentences will not help.

## Proposing changes

Write the improved text, not a description of it. For a short piece, give the
whole revised file; for a long one, the changed parts with enough around them to
place. Keep the author's voice and their decisions: the aim is the same piece
doing its job better, and a rewrite that reads like yours has discarded context
you could not see. Where you would change something the author clearly chose on
purpose, say what you would do and why, and leave the choice to them.

Say how to tell the change worked. For routing, a few requests that should and
should not reach the piece. For a subagent, a representative task run before and
after. A changed instruction is a hypothesis about behavior until someone has
watched the behavior.
