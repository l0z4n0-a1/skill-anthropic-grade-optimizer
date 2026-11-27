# Troubleshooting

Symptom, cause, fix. Only causes the repository's files document are listed. Option lists and exit-code tables are in
[reference.md](reference.md); for how the parts fit together see [architecture.md](architecture.md).

## `/grade-optimizer:grade-optimizer` is not listed

1. The session was open when the plugin was installed or updated. Run `/reload-plugins` or start a new session (the
   README's install steps end with it; Claude Code's documentation, source `cc-plugins-loading` in `kb/sources.json`,
   says the same for any install, update, enable or disable done outside the `/plugin` panel).
2. It is not installed or not enabled. In your shell, `claude plugin list` shows each plugin's id, of the form
   `<name>@<origin>`; this plugin's is `grade-optimizer@l0z4n0-a1-skills` when installed from the README's marketplace.
   The same page says that by default a plugin enabled only in a project's settings does not load until installed on
   your machine, with exceptions (a seed directory, or a relative path in a local marketplace). This is Claude Code
   behaviour taken from its documentation; this repository does not test it.
3. You are using the 2.0 name. In 2.1.0 the skill was renamed from `anthropic-grade-optimizer` to `grade-optimizer`
   because the old name read as if the project spoke for Anthropic, and because Agent Skills upload rules reserve
   `anthropic` and `claude` in names ([changelog](../CHANGELOG.md)). The command is
   `/grade-optimizer:grade-optimizer`; update saved prompts and scripts. The marketplace does not update on its own by
   default: turn on auto-update or run `claude plugin update grade-optimizer@l0z4n0-a1-skills`
   ([README](../README.md#install)).
4. Loading from a clone for one session uses `claude --plugin-dir ./skill-anthropic-grade-optimizer`, as in the README.

Asking in your own words ("audit my setup") can also work, since Claude can select a loaded skill when relevant; nothing
guarantees it will.

## Python is not found

`SKILL.md` says to use `python3`, or `py -3` on Windows, where `python` is not on the path. The requirements are Python
3.9 or later and Claude Code to use the plugin ([README](../README.md#requirements)). Run the same command with
`python3` or `py -3`; the scripts find `kb/` from their own location ([reference.md](reference.md#1-conventions)), but
`measure.py` defaults `--project` to the current directory, so pass `--project` when elsewhere.
If you restrict commands by rule, the rule must cover the name you use: the README's headless example allows
`Bash(python *)`, `Bash(python3 *)` and `Bash(py *)`.

## Claude asks permission every time it runs the measurement script

The README: unless your permission settings already allow it, Claude asks before running the measurement script. The
plugin has no hook or setting that approves it for you (no hooks at all, per [SECURITY.md](../SECURITY.md#what-the-plugin-installs)).

Fix: approve the matching Bash calls through your permission rules. The README's shape is `Bash(python *)` plus the
`python3` and `py` variants. Per Claude Code's documentation (source `cc-permissions`), rules go under
`permissions.allow` in a settings file or are added with `/permissions`; a matching deny or ask rule wins over a more
specific allow, and a project's committed `.claude/settings.json` rules apply only after you accept the workspace trust
dialog. `Bash(python *)` approves every Python command, not only this plugin's scripts, and a Python command can write
files. Rules can name a specific command or script path instead (source `cc-skills`); the README gives none for this plugin.

## A headless run stops or denies a command

A headless run (`claude -p`) cannot ask. Calls that need no approval still run; in Manual mode a call that needs
approval is denied unless a rule, a `PermissionRequest` hook or a permission-prompt tool approves it (source
`cc-headless`). Documented causes:

- A call that needs approval and matches none of your `--allowedTools` rules, such as a shell loop, is denied. The
  review may continue with less evidence. Fix: allow `Read`, `Glob`, `Grep` and the Python rules, as in the README's
  example.
- `Edit` and `Write` are denied on purpose in the example. That does not stop an allowed Python command from writing,
  which is why the rule names Python and nothing broader. Ask for the report on the terminal, as the example does.
- `--bare` skips installed plugins, so pass `--plugin-dir <path>`; Claude Code's documentation lists it as the flag
  that loads a plugin in bare mode. Inference: without it the slash command is not found, since the plugin is not
  loaded.
- Without `--bare`, a `-p` run starts the project's hooks and MCP servers with no trust prompt; `--bare` skips them.
  Run it in a project you trust. This is a safety note, not a cause of denials.

The Agent SDK takes the same settings as options: `plugins`, `allowed_tools`, `disallowed_tools`
([README](../README.md#where-it-runs)).

## `measure.py --compare` refuses a baseline

Each refusal is exit 2, raised before anything is written, so `--out` is untouched; stderr names the reason. From
[reference.md](reference.md#what---compare-requires-of-the-baseline) and [combinations](reference.md#combinations):

| Reason | Fix |
|---|---|
| `--out` and `--compare` name the same file | Write the new measurement to a different file |
| `--piece` used with `--compare` | `--compare` is for setup mode; a piece measurement cannot be a baseline |
| Baseline is not readable JSON, or not an object | Point at the file `--out` wrote |
| `kind` is anything but `"setup"` (a `--piece` measurement, for one) | Take a setup baseline |
| `schema_version` is not the one the script writes (1) | Measure again with this version |
| Required keys missing or mistyped (`fixed_context_est_tokens`, `skills`, `agents`, `description_overlaps`, `settings` with `hooks`; when `usage` is not empty, its session and token numbers and the top-level `never_invoked_in_window` lists) | Measure again |
| `generated`, `read_scope` or `user_config` missing, as in a baseline written before 2.1.0 | Measure again with 2.1.0 or later |
| `home` or `project` differs from the new run | Use the same `--home` and `--project` |
| `--no-external-reads` used in one run and not the other | Use it in both or neither |
| The configured `.claude.json` path differs (`user_config.path`) | Use the same `--user-config` or shell environment |

The last four are refused because the inventories would differ for reasons other than a change to your setup. A
different usage window (`usage.window_days`, set by `--days`) is not a refusal: the usage rows are left out and the
output says so; measure again with the same `--days`.

## `kb_gate.py` exits 3 on a fresh clone

Cause: 3 means "cannot check", not "failed". A fresh clone has no `kb/snapshots/`, because snapshots are other people's
text and are git-ignored ([architecture](architecture.md#snapshots-are-not-committed)); the gate lists them under
`missing_snapshots`. Fix, from the repository root:

```
python scripts/kb_fetch.py --bundled-dir <claude-api skill directory>
python scripts/kb_gate.py
```

Six sources are files of Anthropic's `claude-api` skill. Without `--bundled-dir`, `kb_fetch.py` reports each as a failed
read and exits 1 (the other sources are still written), and the gate keeps exiting 3 naming them: their 135 claims were
not checked ([CONTRIBUTING.md](../CONTRIBUTING.md#checking-quotes)). The
directory is `skills/claude-api` in a clone of [anthropics/skills](https://github.com/anthropics/skills), and is printed
as "Base directory for this skill" when the `claude-api` skill loads in a Claude Code session. `kb_update.py --apply`
also downloads, but only in a working clone with a `.git` entry.

After downloading, three things can still appear. Exit 1 with a quote not found: the span is absent from the current
snapshot. A source changed after the release you cloned is one cause, and the gate is doing its job
([maintaining.md](../references/maintaining.md)); a bad claim or snapshot is another, so check the source before
deciding. It is not yours to fix unless your change is the update. A new `kb/pending.json`, created by `kb_fetch.py` for the changed source; leave it likewise. A
warning, which does not change the exit code: a claim's sentence has a number its source never prints (the changelog
records one for 2.1.0).

## `kb_update.py` exits 1, 3 or 4

Codes are in [reference.md](reference.md#25-scriptskb_updatepy). In practice:

- **3, there is work.** A source changed since the last download, a page was added or removed, or an item is still
  pending. It is not an error. Read which sources changed, how many claims rest on each, and which are first-read or
  measurement claims. A changed source does not mean its claims are wrong, only that nobody has looked since. On an
  installed copy there is nothing to run next: update the plugin when a new version is published and tell the
  maintainer ([commands/update.md](../commands/update.md)). In a clone, follow [maintaining.md](../references/maintaining.md).
- **4, incomplete.** Nothing changed was seen, but the comparison was incomplete: a download failed, an index has no
  baseline, a local snapshot differs from the lock, a lock entry is relocated, or a claim line was unreadable. The JSON
  report names the cause in `failed`, `no_index_baseline`, `snapshot_mismatch` and `relocated`, with a count in
  `unreadable_claim_lines`. Never read 4 as "up to date"; fix the cause and run again.
- **1, nothing could be compared.** A source or index read failed and no comparison completed. No network is one cause
  (`commands/update.md`); `failed` in the report says which reads.

Bundled sources are not compared without `--bundled-dir`; they appear under `not_checked` and `not_compared`, so a clean
run does not mean they were checked. Exit 2 is misuse; the likely cases are `--apply` or `--reviewed` outside a working
clone (no `.git`, under a plugin cache, unwritable `kb/`) and `--out` inside the repository.

## A review or a claim looks wrong

A review is a model's judgment and can be wrong; each finding says how sure it is and how to check
([README limits](../README.md#limits)). To check one that rests on a claim:

1. Print the full record, using the claim id the finding names: `python scripts/kb.py cite hooks-030`. It shows the
   claim, the quote and the source (a link, or a file locator for bundled and local sources). The quote is the source's words; the claim is the plugin's one-line summary. If
   the claim says more than the quote, or drops a condition, it is overstated. The gate cannot catch that, because it
   only checks the quote exists ([reference.md](reference.md#what-it-does-not-check)); on the 60-claim sample for 2.1.0, 11
   claims had an omitted condition or overstated scope ([README](../README.md#what-has-been-measured)).
2. Open the source at the link and read the section around the quote.
3. Look for `[source changed on <date>; claim not re-reviewed]` beside the claim: the source was downloaded again after a
   change and nobody has re-read the claim.
4. A claim that opens by naming a speaker is that person's account of their team's practice, not guidance, and a finding
   should cite it as theirs ([`SKILL.md`](../SKILL.md)).
5. A finding with no claim id should name a principle from [foundations.md](../references/foundations.md) or say
   "judgment"; both are labelled so you can tell them from documented guidance.

If the review says a model is not covered, the knowledge base has no claim tied to that exact model ID. `kb.py models`
lists the IDs it covers. `/grade-optimizer:update` shows how far the sources have moved.

Where to report. A wrong or overstated claim: the repository's "Claim correction" issue form (it asks for the claim id
and what is wrong) or a pull request ([CONTRIBUTING.md](../CONTRIBUTING.md#adding-or-correcting-a-claim)); include the
quote and what the source says. A claim that gets past the gate without a matching quote, or a vulnerability in the
scripts: no public issue; follow [SECURITY.md](../SECURITY.md#reporting-a-vulnerability). A secret in the measurement
output is different: SECURITY.md documents that copied fields, hook commands included, can already contain secrets, so
check what you share.
