# Notice: what the license covers, and what belongs to others

This project is independent. It is not affiliated with, endorsed by or
sponsored by Anthropic. "Claude" and "Anthropic" are Anthropic's names and are
used here only to say what the tool reviews.

## What the MIT license covers

The [LICENSE](LICENSE) applies to the original material in this repository:
the scripts, the guides under `references/`, `SKILL.md`, the command, the
tests, the eval fixtures, and, in the knowledge base, the wording of each
`claim`, `why` and `check` field and the selection and arrangement of the
records.

## What it does not cover

Each record in `kb/claims/` carries a `quote` field: a short verbatim excerpt
from the source it summarises, kept so that a script and a reader can check
the claim against the page. Those excerpts remain the property of their
authors and are not licensed to you by this repository. They are included for
citation and verification, each with a link or a reference to where it came
from.

As of version 2.1.0 the knowledge base holds 1,569 excerpts from 142 sources,
with a median length of 145 characters and none longer than 400:

| Where the excerpts come from | Sources | Excerpts |
|---|---|---|
| Anthropic's Claude Code and Claude platform documentation | 93 | 1,009 |
| Reference files of Anthropic's `claude-api` skill (Apache License 2.0, see below) | 6 | 135 |
| Posts and articles Anthropic publishes under its own name | 42 | 407 |
| A conversation with Anthropic staff published by a third party (simonwillison.net) | 1 | 18 |

`kb/sources.json` lists every source. The full text of the sources is never
stored in this repository: the snapshots the quote check reads are downloaded
to a directory that git ignores.

### The `claude-api` excerpts

The six `bd-*` sources are files of the `claude-api` skill, published by
Anthropic at
[github.com/anthropics/skills](https://github.com/anthropics/skills/tree/main/skills/claude-api)
under the Apache License 2.0. A copy of that license is at
[LICENSES/Apache-2.0-claude-api.txt](LICENSES/Apache-2.0-claude-api.txt). The
excerpts are reproduced verbatim, unmodified, each with the path of the file
it comes from.

### The other excerpts

The excerpts from documentation, posts and the published conversation are
short quotations, attributed and linked, used to let a reader verify what a
claim says. This project relies on that use being a permitted quotation; it
holds no licence from their authors.

If you redistribute the knowledge base, the excerpts travel with it, and
whether your use of them is permitted is for you to decide under the law that
applies to you. If you hold rights in a quoted source and want an excerpt
removed, open an issue or write to the address in [SECURITY.md](SECURITY.md).
The quote will be deleted; the claim will either be deleted too or reworded
and pointed at another source that supports it.
