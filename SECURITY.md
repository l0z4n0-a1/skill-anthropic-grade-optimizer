# Security Policy

## Supported versions

Only the latest minor version of `grade-optimizer` receives security fixes.

| Version | Supported |
|---|---|
| 2.1.x | yes |
| 2.0.x and earlier | no |

## Reporting a vulnerability

If you find a security issue, for example a way to make `measure.py` write a
secret from a settings file or text from a session into its output, a way to
get a claim past `kb_gate.py` without a matching quote, or a way to make the
update scripts contact a host outside their list, please do not open a public
GitHub issue.

Instead, email the maintainer at **fluxmind.ia@gmail.com** with:

- A short description of the issue and impact.
- A minimal reproduction (command, input, observed behavior).
- Your suggested mitigation, if you have one.

You can expect an acknowledgment within 7 days. Coordinated disclosure is
preferred; the maintainer will work with you on a release timeline before any
public disclosure.

## What the plugin installs

One skill, one user-invoked command, and Python scripts that run only when
Claude, with your permission, or you run them. No hooks, no MCP server, no
background process, no executable in `bin/`, no dependency outside the Python
standard library.

## What the scripts touch

**`measure.py` reads; it has no network code.** By default it reads:

- the Claude Code user directory (`~/.claude`, or `CLAUDE_CONFIG_DIR`, or
  `--home`): instruction files, skills, agents, commands, settings files,
  the plugin install records, and the session transcripts under it, which
  cover every project whose sessions that directory holds;
- the project directory given with `--project`, and the instruction files in
  its parent directories, as Claude Code itself loads them;
- files those instruction files import, wherever they point, and the
  directories of enabled plugins, following symlinks;
- the user-level `.claude.json`, for the names of configured MCP servers.

`--no-external-reads` keeps it inside `--home` and `--project`, for reviewing a
setup you did not write.

From what it reads, it copies into its output the values of a fixed list of
frontmatter fields and settings, hook definitions, permission rules, and the
names of servers, plugins, models, tools, skills and agents. It never copies
the values of `env` entries, the arguments of MCP servers, message text, or a
frontmatter field outside the list. What it copies, it copies as written: if
a description, a hook command or a permission rule embeds a secret, that
secret appears in the output. So:

- write the output outside any repository, and treat it like the files it was
  read from. `--out` creates the file readable by the current user only where
  the system supports that; on Windows the folder's inherited permissions
  apply;
- opening the output in a Claude session sends its contents to that session.

**`kb_update.py` and `kb_fetch.py` use the network.** They request the source
URLs in `kb/sources.json` and two documentation index pages, with a generic
User-Agent, and send nothing from the machine or the setup. A redirect to a
host outside that list is refused. As with any request, the hosts see your IP
address and the time. `kb_update.py` without `--apply` writes nothing inside
the plugin. `kb_fetch.py --list <url>` requests the URL you give it and
follows redirects only within that URL's host.

**`kb.py` and `kb_gate.py`** read the repository's own `kb/` directory and
nothing else.

No script executes anything from the setup under review. Hooks, skills and
agents are read as text.

## Reviewing a setup you did not write

The review reads instruction files, skills and agent definitions, and those
can contain text aimed at the model reading them. The skill treats what it
reads as material to assess, and the documentation snapshots the update
command reads the same way. That is an instruction to a model, not a
boundary. Review an untrusted setup in a session without permissions you
would not hand to its author, and measure it with `--no-external-reads`.

## Out of scope

- Misconfiguration on the operator side, such as sharing a measurement file
  that contains hook commands with embedded credentials.
