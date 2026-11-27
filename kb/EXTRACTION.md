# Extracting claims into the knowledge base

This is the brief for whoever (a person or an agent) turns source snapshots into
claims. It is used when the knowledge base is first built and every time a source
changes, for instance when a new Claude model ships.

## What the knowledge base is for

An auditor reads a user's Claude Code setup (instruction files, skills, subagents,
hooks, settings, MCP servers, plugins, and how they are used) and says where it
falls short of what Anthropic documents and recommends, and what to change to get
more out of the model for less context and cost. The auditor is a current Claude
model. It is good at judgment and does not need rules for what it already knows.
It needs the facts and recommendations it could get wrong from memory: how the
harness really behaves, what each current model does differently, what Anthropic
says to do and why.

So a claim earns its place when it would change an audit verdict. Ask of each
candidate: would an auditor who did not know this reach a different conclusion
about some setup? If not, leave it out. General prompting advice a capable model
already follows is not a claim. A number, a limit, a load order, a default, a
behavior that differs between models, a recommendation with a stated reason: those
are claims.

## The record

One JSON object per line, in `kb/claims/<your-file>.jsonl`:

```json
{"id": "skills-012", "topic": "skills", "kind": "fact", "applies_to": ["claude-code"], "claim": "…", "why": "…", "check": "…", "quote": "…", "source": "cc-skills"}
```

- `id`: `<prefix>-<number>`, written with three digits (`skills-012`), unique
  across the whole knowledge base and never reused. Use the prefix and number
  range you were given; working alone, use the prefix of the file you are adding
  to and the next unused number. The prefix is a namespace that keeps parallel extractors
  from colliding; it often matches the topic but does not have to, and `topic` is
  the field that queries select on.
- `topic`: one of `prompting`, `model`, `context`, `cost`, `skills`, `subagents`,
  `hooks`, `mcp`, `plugins`, `settings`, `orchestration`, `tools`, `evals`, `harness`.
- `kind`: `fact` (how the harness or API behaves), `behavior` (how a model
  behaves), or `practice` (what Anthropic recommends doing).
- `applies_to`: a list. `["claude-code"]` for harness facts, `["all"]` for advice
  that holds across current models, or model ids such as `["claude-opus-5-5"]`
  when the source ties the statement to specific models. When the source names a
  model, keep the name: the same advice can be wrong for the next model.
- `claim`: one sentence, in your own words, that stands on its own. Name the thing
  it is about; a reader sees this sentence without the source.
- `why`: the reason the source gives, in one sentence. If the source gives no
  reason, write what follows from the claim for someone configuring a setup.
- `check`: one sentence saying what an auditor would look at in a real setup
  because of this claim, and what would count as a problem.
- `quote`: a span copied character for character from the snapshot, 25 to 400
  characters, that supports the claim. Copy it; do not retype, trim words from the
  middle, or fix its punctuation. Prefer a span without markdown links or table
  pipes, since those must match exactly too. A script checks that the quote
  appears in the snapshot, and a claim whose quote is not found is rejected.
- `source`: the source id, which is the snapshot's file name without `.md`.

## How to work

Read each assigned snapshot in `kb/snapshots/`. Long files are read in parts; read
all of the parts you were assigned. Write claims as you go, appending to your file,
so a long run leaves usable output if it is interrupted.

Prefer fewer, sharper claims. When two sources say the same thing, keep the one
with the clearer reason. When two sources disagree, or a source contradicts
itself, keep both claims and say so in each `why`: a disagreement between official
sources is itself something the auditor must know.

A number in a claim is one the source prints. Do not add up a table, turn two
figures into a percentage, or supply a year the page does not give: a derived
number passes the quote check and is still yours, not the source's. If the
arithmetic matters, state the source's figures and let the reader do it.

Record what the source says, including when it surprises you. Your memory of how
Claude Code or a model behaves may be older than the snapshot; where they differ,
the snapshot is the evidence.

## What to send back

A short summary: how many claims you wrote, the path of your file, the five
claims you think matter most for auditing a setup, anything in the sources that
contradicts another source or looked wrong, and any assigned file you could not
read in full.
