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

**`backup.py` reads and writes the files you name, and nothing else.** `save`
copies them into a backup folder (default `~/.grade-optimizer-backups`, outside
`~/.claude` and any project); `restore` writes them back. The copies can hold
secrets from your settings files: the folders and files are created readable by
the current user only where the system supports that, and on Windows they take
the permissions of their folder (the script does not set an ACL there, and a
file it writes back takes its folder's inherited rules, not any per-file ACL
the original had). Each backup also holds a copy of `backup.py`, so a restore
does not depend on the plugin staying installed. `restore` is atomic per file,
not across files: it checks every file first and refuses the whole run if a
path now resolves somewhere other than where it was recorded (a parent folder
turned into a symlink or junction) or a file changed since the edit, but if a
write then fails on one file the others are still restored and the exit is 1;
running it again finishes the job. It prints no file contents and has no
network code.

What these scripts do not defend against, by design: another program writing
the same file in the instant between a check and the write that follows it.
`settings_edit.py --expect-sha256` and the restore's change check narrow that
window to the time of one write; they do not lock the file. Run an upgrade or
a restore with no other Claude Code session editing the same setup. A settings
file is rewritten as JSON with its values intact, but numbers are written in
their shortest exact form (`1.50` becomes `1.5`) and indentation is
normalized; a file that cannot be rewritten without changing a value
(duplicate keys, numbers out of range) is refused.

**`settings_edit.py` reads and writes the one settings file you name, and nothing
else.** It makes six kinds of edit (hooks, permission rules, a few plain
settings) and prints only the part it changed, so the rest of the file, which
can hold secrets, is never shown. A hook command or permission rule is never
printed beyond one rule: for a hook command, the program name and the base name
of the first script-like argument, then `…`, never the rest of the command,
quoted or not. A permission rule keeps its tool name and a short plain
specifier, and otherwise the tool name and two words; a rule is judged by shape,
not by a search for credentials, so a short bare secret in its first two words
would be shown. `measure.py` applies the same rules to the hook commands and
permission rules in its JSON. It prints the canonical path it will write and the
file's sha256, and `--expect-sha256` makes a write refuse if the file changed
since a dry run. It refuses a path that goes through a symlink or junction
unless `--follow-links`, and refuses, without echoing, a file that is not valid
JSON or cannot be written back unchanged (repeated keys, numbers out of range,
`NaN`). It writes atomically and has no network code.

**`check_upgrade.py` executes the guard scripts of the fixture it checks**, in a
temporary copy, with a 10-second limit and a minimal environment (no inherited
credentials). It never uses a shell: it splits the configured command with
`shlex`, expands only `~`, `$HOME` and `$CLAUDE_PROJECT_DIR` to the copy's paths,
runs only `python`, `python3` or `py` (replaced by its own interpreter)
on a script whose resolved path is inside that copy, and reports anything else
as `not exercised`. It is still the setup's own code running as you: point it at
a fixture you built.

Apart from `check_upgrade.py` on a fixture, no script executes anything from
the setup under review. Hooks, skills and agents are read as text.

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
