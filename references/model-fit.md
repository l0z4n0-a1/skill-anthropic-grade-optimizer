# Fitting a setup to a model

Instruction text is written against the behavior of the model that was reading
it at the time. When the reader changes, some of that text stops helping and
some starts to hurt: emphasis added for a model that under-reacted now causes
over-reaction, steps added for a model that planned poorly now override better
plans, and a new model's own habits go unaddressed because nobody has written
for them yet. Fitting a setup to a model means finding all three.

## Which model reads what

A setup is often read by several models at once. The main session runs one;
each subagent runs the one it pins, or the main session's if it pins none; a
skill may pin its own. The measurement shows what each agent declares and, in
the usage block, which models actually served requests. Establish from the
request and the measurement which model is the target and which pieces it reads,
and state that at the top of what you report. Review a piece that pins a model
against that model, not the target.

Check that the knowledge base covers the target: `kb.py models`. If the model is missing, the knowledge base
does not cover it, whatever the reason. Say so, read the model's prompting guide and what's-new page from
the current documentation for this review, and point the person to
`references/maintaining.md`.

## What to read

`kb.py model <target id> --brief` lists every claim tied to the target, and
`kb.py cite <ids>` expands the ones you act on. They cover
what it does by default, how its effort levels behave, which older instructions
its documentation says to re-test or remove, and which new instructions it
recommends, often with suggested wording. If the person is coming from a
specific model, read that one's claims too. The difference between the two
lists is the migration.

## What to look for

**Settings that changed meaning.** Effort is the main one. Level names do not
carry across models, defaults differ between models and between the API and
Claude Code, and the documentation for several current models says effort
controls thinking and cost more reliably than prompt text does. Anything in the
setup that leaves effort unset, or that sets a level tuned on another model, is
a choice to revisit. Check frontmatter fields and settings against the claims
for anything the target rejects or treats differently.

**Text the target no longer needs.** The claims name, per model, the kinds of
instruction that were written for its predecessors. Search the instruction
files, skills and subagent prompts for them. Removal is a hypothesis: propose
it, and say what behavior to watch to confirm nothing was lost. For the general
patterns of dated text that are not specific to one model,
`/doctor prompt-audit` covers them across every file.

**Text the target needs and the setup lacks.** This is the half that gets
skipped. Each current model has documented habits that the right sentence
tunes, and its documentation supplies the sentence. Propose adding one only
where the setup shows the behavior it addresses, or where the person's work is
the kind the documentation says is affected, because each addition has a cost
the claims also record, in tokens or in changes nobody asked for.

**Roles that should move.** A new model changes which tier suits which work.
Where the target is cheaper or stronger than what a role uses now, or where its
documentation recommends against a kind of work, say so, as something to try
and measure.

**The exact wording.** Where a claim says the documentation recommends a
sentence or paragraph, the claim's quote holds only its opening, since quotes
are short. Take the full text from the source page that `kb.py cite` links,
and give the person that text with the link. Do not reconstruct it from the
opening.

**Money.** The knowledge base does not track prices, which change. When the
person asks what a move will save, point them to `/usage` for what they spend
now and to the current pricing page for rates, and compare cost per finished
task, not per token. Do not compute a saving from remembered prices.

**What is not about the model.** Reading a setup closely turns up problems that
would exist on any model. Report the ones that matter, briefly and in their own
section, so the person does not take them for part of the migration.

## What to keep

Nearly everything. Context about the project, the audience, the quality bar and
the reasons behind constraints does not depend on the reader's generation, and a
migration that shortens it has removed the most valuable words. Confirmation
steps before risky or irreversible actions stay regardless of what any model's
documentation says about caution. Change what the claims give you a reason to
change, and leave the rest.

## Reporting

Give the person three lists: what to change in settings, what to remove or
rewrite, and what to add, each item with the claim it rests on and a way to
check it. Recommend making the changes in small groups and watching real work
between them, so that if something gets worse they can tell which change did it.
