# Security Policy

## Supported versions

Only the latest minor version of `anthropic-grade-optimizer` receives security
fixes.

| Version | Supported |
|---|---|
| 2.0.x | yes |
| 1.x | no |

## Reporting a vulnerability

If you discover a security issue, for example a way to make `measure.py` write
a secret from a settings file or text from a session into its output, or a way
to get a claim past `kb_gate.py` without a matching quote, please do not open a
public GitHub issue.

Instead, email the maintainer at **fluxmind.ia@gmail.com** with:

- A short description of the issue and impact.
- A minimal reproduction (command, input, observed behavior).
- Your suggested mitigation, if you have one.

You can expect an acknowledgment within 7 days. Coordinated disclosure is
preferred; the maintainer will work with you on a release timeline before any
public disclosure.

## What the scripts touch

- `measure.py` reads the Claude Code directory and one project directory on the
  local machine and makes no network call. From settings files it records key
  names, hook definitions and counts, and never the values of `env` entries or
  the arguments of MCP servers. From session history it records counts and token
  totals, and never message text. Hook commands are recorded as written; if a
  hook command embeds a secret, that secret appears in the output file, so treat
  the JSON as you would the settings file itself.
- `kb_fetch.py` is the only script that uses the network. It requests the URLs in
  `kb/sources.json` with a generic User-Agent and sends nothing about the machine
  or the user.
- No script executes anything from the setup under review. Hooks, skills and
  agents are read as text.

## Reviewing a setup you did not write

The review reads instruction files, skills and agent definitions, and those can
contain text aimed at the model reading them. The skill treats what it reads as
material to assess. Even so, review an untrusted setup in a session without
permissions you would not hand to its author.

## Out of scope

- Misconfiguration on the operator side, such as sharing a measurement file that
  contains hook commands with embedded credentials.
