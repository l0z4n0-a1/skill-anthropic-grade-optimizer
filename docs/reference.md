# Reference

This page documents every script in `scripts/` and `evals/`, and every data file in `kb/`.
It covers options, exit codes, output format, and what validates each file.

Paths are relative to the repository root unless they are absolute.

Contents:

1. Conventions
2. Scripts: `measure.py`, `kb.py`, `kb_gate.py`, `kb_fetch.py`, `kb_update.py`, fixture builders
3. Data files
4. Limits fixed in code

## 1. Conventions

- Python 3.9 or later. Standard library only. No package to install.
- Run a script as `python scripts/<name>.py` from the repository root, or with a full path. The scripts find `kb/` from their own location, not from the current directory. `kb.py` and `kb_update.py` import their sibling scripts, so keep `scripts/` intact.
- All text files are UTF-8. The scripts reconfigure stdout to UTF-8 where the stream allows it.
- `measure.py` and `kb_update.py` write JSON that carries `"schema_version": 1`. The version is an integer. In `measure.py` it is raised only when a key is removed or changes meaning. In `kb_update.py` a key is never removed within a version. In both, new keys can appear without a bump, so ignore keys you do not know.
- `kb_gate.py --json` has no `schema_version`. Its four keys are listed in the `kb_gate.py` section.
- Text output is for people and may change between releases. JSON is the stable surface. `kb.py` has no JSON mode.
- Network access: only `kb_fetch.py` and `kb_update.py` use it. `measure.py`, `kb.py` and `kb_gate.py` never do.

## 2. Scripts

### 2.1 `scripts/measure.py`

Measures a Claude Code setup: which pieces exist (instruction files, skills, subagents, commands, rules, output styles, plugins, settings, hooks, MCP servers), when each loads, what it costs in estimated tokens, and how it was used in recent session history. It counts and lists; it does not judge. It reads local files only and makes no network call. It writes nothing except the file named by `--out`.

Two modes:

- Setup mode (default) measures a whole setup.
- Piece mode (`--piece`) measures one skill or subagent file on its own, whether or not it is installed.

#### Options

| Option | Argument | Default | Meaning |
|---|---|---|---|
| `--home` | `DIR` | `$CLAUDE_CONFIG_DIR`, else `~/.claude` | User-level Claude Code directory. Must exist. |
| `--project` | `DIR` | current directory | Project directory. Must exist. |
| `--days` | `N` | 30 | Days of session history to read. `0` skips history. Accepted range 0 to 36500. |
| `--out` | `FILE` | none | Also write the full JSON to this file. The directory must exist. The file is created with mode 0600 where the system has modes. On Windows the mode has no effect and the file takes the ACL of its folder. |
| `--compare` | `FILE` | none | A setup JSON written earlier with `--out`. Also prints what changed. |
| `--piece` | `PATH` | none | A skill folder (one holding `SKILL.md`), a `SKILL.md` file, or a subagent `.md` file. |
| `--user-config` | `FILE` | see below | The user-level `.claude.json`. Must exist if given. |
| `--no-external-reads` | none | off | Read nothing whose resolved path is outside `--home` and `--project`. |

Where the user-level `.claude.json` is looked for, in order: `--user-config`; inside `--home` when `--home` is the `CLAUDE_CONFIG_DIR` of the current shell; beside `--home` when `--home` is named `.claude`; otherwise inside `--home`. The output field `user_config.basis` says which rule applied. Only server names and transports are read from it.

#### Combinations

- `--piece` takes only `--out` and `--no-external-reads`. `--home`, `--project`, `--days`, `--user-config` and `--compare` are refused with it (exit 2).
- `--out` and `--compare` must name different files. Otherwise `--out` would replace the baseline before it is read (exit 2).
- `--compare` applies to setup mode only. A `--piece` measurement cannot be a baseline.

#### What `--compare` requires of the baseline

The file given to `--compare` must satisfy all of the following, or the run exits 2 before measuring:

- It is readable JSON, and an object.
- `kind` is `"setup"`.
- `schema_version` equals the version the script writes (1).
- `fixed_context_est_tokens` is an object, `skills` and `agents` and `description_overlaps` are lists, and `settings` is an object.

After the new measurement is made, `home` and `project` of the baseline must equal those of the new run (compared with the platform's case rules). A different pair exits 2.

If the two runs used different history windows (`usage.window_days`), the usage rows are left out of the comparison and the output says so. Measure again with the same `--days`. The comparison is printed after the summary. It is not written to `--out`.

#### Exit codes

| Code | Meaning |
|---|---|
| 0 | Measured. Problems with single files are listed under `unreadable` and are not fatal. |
| 1 | The measurement was made but `--out` could not be written (I/O error). The summary still printed. |
| 2 | The command line or an input cannot be used: bad flag or combination, a nonexistent `--home`, `--project`, `--piece` or `--user-config`, a `--piece` that is not a skill or subagent file, an invalid `--compare` baseline, `--out` naming a folder or a missing folder, `--days` out of range. A message on stderr says what to change. |

There is no precedence between codes: 2 is raised before any measurement is made, and 1 only after.

#### Output

Setup mode writes the full JSON to `--out` (if given) and prints a short text summary to stdout. Piece mode prints the JSON to stdout and also writes it to `--out`.

Units used throughout:

- `chars` and keys ending in `_chars` count characters of the decoded text, not bytes.
- `est_tokens` is characters divided by 4, rounded. It is an estimate.
- Figures under `usage` are token counts that Claude Code logged.
- Shares are fractions from 0 to 1 rounded to 4 places, or `null` when there is nothing to divide.
- `generated` is a UTC timestamp.
- Paths are written as the system prints them.

##### Setup report, top-level keys

| Key | Type and shape | Absent or null when |
|---|---|---|
| `schema_version` | integer, 1 | never |
| `kind` | `"setup"` | never |
| `generated` | UTC ISO timestamp, seconds | never |
| `home`, `project` | string, path | never |
| `user_config` | `{path, basis, found}`; `found` is a boolean | `found` is false when the file is missing or outside the read scope |
| `read_scope` | `{confine_external_reads: bool, skipped_outside_scope: [path]}` | list empty unless `--no-external-reads` declined reads; capped at 50 paths |
| `policy` | object, see below | never |
| `estimate_note` | string | never |
| `not_measured` | list of strings | empty list is possible |
| `skill_listing_cap` | `{chars, source}` | never |
| `instruction_mode` | `{value, source, note}` | `note` is null unless the settings name a mode that is ignored or unknown |
| `fixed_context_est_tokens` | `{instruction_files, rules_without_paths, skill_listing, agent_listing, active_output_style, total}`, integers | never |
| `instruction_files` | list of `{path, scope, imported_by, chars, lines, est_tokens, loads, external}` | empty list |
| `skills` | list of skill records | empty list |
| `agents` | list of agent records | empty list |
| `commands`, `rules`, `output_styles` | lists of `{name, scope, path, chars, est_tokens, frontmatter, other_fields, parse_notes}`; rules also carry `loads` | empty list |
| `plugins` | list of `{id, name, enabled, decided_by, installs}`, plus `note` for a plugin enabled with no install record | empty list |
| `settings` | `{files, hooks, mcp_servers}` | lists empty |
| `description_overlaps` | list of `{a, b, jaccard, shared}`, most similar first | empty list |
| `usage` | object, see below | `{}` when `--days` is 0 or `<home>/projects` does not exist |
| `never_invoked_in_window` | `{skills: [qualified name], agents: [qualified name]}` | `{}` when `usage` is `{}` |
| `spawned_without_definition_here` | list of agent type names | empty list |
| `unreadable` | list of strings, one per problem file | empty list |

Records of pieces (skills, agents, commands, rules, output styles) carry `parse_notes`, a list naming what the line-based frontmatter reader saw but did not interpret. Skill records also carry `description_source`, which says whether the description came from frontmatter, from the first non-empty body line, or was missing.

Skill record fields: `name`, `qualified`, `scope`, `path`, `frontmatter`, `other_fields`, `parse_notes`, `description_source`, `visibility` (one of `on`, `name-only`, `user-invocable-only`, `off`), `model_invocable`, `listing_chars`, `listing_truncated`, `always_est_tokens`, `body_lines`, `on_invoke_est_tokens`, `bundled_files`.

Agent record fields: `name`, `qualified`, `scope`, `path`, `frontmatter`, `other_fields`, `parse_notes`, `model` (`"(inherits)"` when unset), `effort` (`"(unset)"`), `tools` (`"(all)"`), `listing_chars`, `always_est_tokens`, `body_lines`, `on_spawn_est_tokens`.

`policy` echoes the named constants that decide how the report is cut. They are presentation choices, not facts about Claude Code. Keys: `default_days`, `chars_per_token`, `overlap_top`, `overlap_min_jaccard`, `overlap_min_words`, `overlap_min_word_chars`, `overlap_common_share`, `overlap_common_min_pieces`, `overlap_shared_shown`, `top_tool_results`, `max_value_chars`, `max_scalar_chars`, `max_rule_chars`, `max_rules_per_list`, `name_max_chars`, `rebuild_share`, `compaction_shrink`, `tail_bytes`. Values are in section 4.

`not_measured` lists, as sentences, what the script does not read or apply. Some entries are fixed (the built-in system prompt, MCP tool definitions, bundled skills, auto memory, managed settings, hooks defined by plugins or frontmatter, the skill listing budget, marketplace manifests, the YAML subset of the frontmatter reader). Others are added when they apply: plugin manifests that name paths, `claudeMdExcludes` patterns, an ignored instruction mode, instruction files above the project, unresolved imports, files declined under `--no-external-reads`, transcript rows whose timestamp had no offset, and plugin install entries that were not counted.

`usage` keys:

| Key | Shape |
|---|---|
| `window_days` | integer |
| `scope`, `transcript_root`, `attribution` | strings |
| `coverage` | object of counters: `files_found`, `files_read`, `files_wholly_before_window`, `files_outside_scope_skipped`, `naive_timestamps_read_as_utc` (only counters that were touched appear) |
| `sessions` | `{main, subagent}`, counts |
| `tokens_by_scope_and_model` | `{"<scope> \| <model>": {input, cache_write, cache_read, output, requests}}` |
| `tokens_total` | `{input, cache_write, cache_read, output, requests}` |
| `avg_prompt_tokens_per_request` | `{scope: integer}` |
| `cache_read_share_of_prompt_tokens`, `subagent_share_of_output_tokens`, `share_of_spawns_to_agents_defined_here` | fraction, or null |
| `tool_calls`, `skill_invocations`, `typed_commands`, `agent_spawns` | `{name: count}`, most common first |
| `agent_runs` | `{agent: {runs, models, requests_per_run, output_tokens_per_run, prompt_side_tokens_per_run, output_tokens}}` |
| `cache_rebuilds` | `{definition, basis, main_requests_considered, by_cause: {cause: {count, tokens_rewritten}}}`; the cause is an inference |
| `main_cache_write_tokens_by_lifetime` | `{short, long}`, tokens |
| `tool_result_chars` | `{tool: characters}`, top 12 tools |
| `requests_by_model_and_effort` | `{"<model> @ <effort>": count}` |
| `attribution_ambiguous` | `{skills: [name], agents: [name]}`; bare names that fit several pieces |

Names in history are matched to pieces by qualified name (`plugin:skill`). A bare name that fits several pieces credits all of them and is listed under `attribution_ambiguous`.

##### Piece report, top-level keys

| Key | Meaning | Absent when |
|---|---|---|
| `schema_version`, `kind` | 1 and `"piece"` | never |
| `piece_type` | `"skill"` or `"agent"` | never |
| record fields | the same fields as an entry of `skills` or `agents`, at the top level; `scope` is `"standalone"` | never |
| `bundled` | `{folder: {files, est_tokens}}` for `.md` and `.txt` files in subfolders of the skill folder | agents |
| `estimate_note`, `policy` | as in the setup report | never |
| `not_measured` | list of strings; includes that history is not read and that `skillListingMaxDescChars` and `skillOverrides` of the destination setup are not applied | never |
| `unreadable` | list of strings | empty list |

#### Scope of a setup measurement

- Pieces come from the user level, the given project (its `.claude/` folder), and each enabled plugin.
- A plugin is enabled when its entry in the effective settings is true. Settings are read from user, then project, then local; a later `false` undoes an earlier `true`.
- An install entry of scope project or local counts only for the project named in its `projectPath`. Scope user or managed always counts.
- A plugin skill is a folder under the plugin's `skills/`, or, when the plugin has no `skills/` folder and its manifest has no `skills` key, a `SKILL.md` at the plugin root.
- Usage covers the recognized transcripts under `<home>/projects`, every project folder there, because user-level pieces serve all of them. An agent with no definition here is listed under `spawned_without_definition_here`.
- Instruction files are `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, `AGENTS.md` and `.claude/AGENTS.md` in the project directory and in every directory above it, plus `<home>/CLAUDE.md`. Files named by `@path` imports are followed to four hops, wherever they are, and symlinks are followed.
- Hook script paths are checked for existence. Their contents are not read.

`--no-external-reads` drops every read whose resolved path is outside `--home` and `--project`: ancestor directories, imports and symlink targets elsewhere, plugin folders elsewhere, and a `.claude.json` beside `--home` unless `--user-config` names it. What it declined is listed under `read_scope` and `not_measured`.

#### What the script never copies

It copies a fixed list of frontmatter fields and settings, hook definitions, permission rules, and the names of servers, plugins, models, tools, skills and agents. It never copies `env` values, MCP server arguments, message text, or any frontmatter field outside the list. Environment variable names are kept, values are not.

What it does copy, it copies as written. A secret typed into a description, a hook command or a permission rule appears in the output. Treat the JSON like the files it was read from.

Frontmatter fields kept (constant `SAFE_FIELDS`): `name`, `description`, `when_to_use`, `model`, `effort`, `tools`, `disallowedTools`, `allowed-tools`, `disable-model-invocation`, `user-invocable`, `context`, `agent`, `paths`, `permissionMode`, `maxTurns`, `skills`, `memory`, `background`, `isolation`, `color`, `argument-hint`, `version`, `license`. Other field names are recorded under `other_fields`, without values.

Settings keys kept (`SAFE_SETTINGS`): `model`, `outputStyle`, `effortLevel`, `autoCompactWindow`, `cleanupPeriodDays`, `disableBundledSkills`, `alwaysThinkingEnabled`, `autoMemoryEnabled`, `skillListingMaxDescChars`. Hook options kept (`SAFE_HOOK_OPTIONS`): `onFailure`, `async`, `once`, `continueOnBlock`, together with `command`, `type`, `timeout` and `matcher`.

### 2.2 `scripts/kb.py`

Reads the knowledge base and prints the claims that matter for one review. It selects by topic and by model. It reads local files only, writes nothing, and does not run the gate. Read in two passes: `--brief` for one line per claim, then `cite` for the full record of the claims that matter.

Input: `kb/claims/*.jsonl`, `kb/core.json`, `kb/sources.json`, `kb/snapshots.lock.json`, and `kb/pending.json` if present. Output: text on stdout. Its layout is not a stable interface.

A claim whose source is listed in `kb/pending.json` carries a note: `[source changed on <date>; claim not re-reviewed]`.

#### Commands

| Command | Arguments | Prints |
|---|---|---|
| `topics` | none | each topic with its claim count, then a total |
| `models` | none | each model id that has model-specific claims, with counts |
| `show` | `TOPIC[,TOPIC...]` and options below | claims of those topics that apply to every model, plus those tied to the models named with `--model` |
| `model` | `ID`, optional `--brief` | every claim whose `applies_to` names that model id |
| `core` | optional `QUESTION` | with no argument, the questions in `kb/core.json`; with one, its principle and its core claims |
| `cite` | `ID` ... (separated by commas or spaces) | the full record of each claim, with quote and source |

`show` options:

| Option | Argument | Default | Meaning |
|---|---|---|---|
| `--model` | `ID[,ID...]` | none | Include claims tied to these model ids. Claims tied only to other models are left out. |
| `--kind` | `fact`, `behavior` or `practice` | all | Only claims of this kind. |
| `--grep` | `TEXT` | none | Only claims whose `claim`, `why` or `check` contains the text, case-insensitive. |
| `--quotes` | none | off | Include each claim's quote and source. |
| `--brief` | none | off | One line per claim: id and claim only. |

`model` takes only `--brief`. Spaces around the commas of a list are ignored. A claim applies to every model when its `applies_to` contains `all` or `claude-code`.

A model id that no claim names is not an error for `show`. The script says so on stderr and prints the general claims. For the `model` command the same situation is an empty selection (exit 1).

#### Exit codes

| Code | Meaning |
|---|---|
| 0 | Claims printed. |
| 1 | The selection is valid and empty: nothing matches, or `model` names an id no claim names. |
| 2 | Invalid value or usage: unknown topic, claim id, core question or kind; a model id that is not shaped like one (`all` and `claude-code` are refused here); bad arguments. |
| 3 | Knowledge base data is missing or malformed. The message points to `kb_gate.py`. |

### 2.3 `scripts/kb_gate.py`

The gate for the knowledge base. Every claim must quote its source verbatim. It reads local files only, writes nothing, and uses no network. The exit code is the verdict.

Input: `kb/claims/*.jsonl`, `kb/sources.json`, `kb/snapshots/<source id>.md`, and, when present, `kb/snapshots.lock.json`, `kb/index.lock.json` and `kb/pending.json`.

Usage: `kb_gate.py [--json] [FILE ...]`

| Option | Argument | Default | Meaning |
|---|---|---|---|
| `--json` | none | off | Print the result as JSON instead of text. |
| `FILE` | claim file paths, zero or more | all of `kb/claims/*.jsonl` | Check only these files. This is limited coverage: say so when you report it. Claim ids are still checked for uniqueness against every file in `kb/claims/`. |

Text output: one line per file with its verified count, a totals line (`total verified=... errors=... missing_snapshots=... warnings=...`), then one line per error (`x`), warning (`!`) and missing snapshot (`?`).

JSON output (no `schema_version`):

| Key | Type | Meaning |
|---|---|---|
| `ok` | object, `{file name: verified count}` | Claims that passed, per file. |
| `errors` | list of strings | Each problem found. |
| `warnings` | list of strings | Claims to read again. Never affect the exit code. |
| `missing_snapshots` | list of source ids, sorted | Sources whose snapshot file is absent. |

#### What it checks

- `kb/sources.json` is a list; each entry has a unique id, exactly one locator, a valid tier and a non-empty topic (section 3.2).
- `kb/snapshots.lock.json` entries are well formed and name known sources (section 3.5). `kb/index.lock.json` and `kb/pending.json` have the right shape (sections 3.6 and 3.7). A source named in `pending.json` must exist in `sources.json`.
- Each claim line is valid JSON with all required fields, in the right types and with allowed values (section 3.1).
- Each claim id is unique across all of `kb/claims/`.
- Each claim's source exists in `sources.json`.
- The quote is 25 to 400 characters after normalization, and holds at least 18 letters or digits.
- The quote appears in `kb/snapshots/<source>.md`, after both are normalized: typographic single and double quotes, en and em dashes and the non-breaking hyphen become their ASCII forms, and runs of whitespace collapse to one space. The match is case-sensitive. Markdown markers are part of the text, so quote the source as written or pick a span without markup.
- A snapshot's SHA-256 equals the one in the lock. A difference is an error, because the snapshot is then not the text the lock recorded. The claims are still checked against it.
- At least one claim was checked. An empty knowledge base is not a pass.

Warning: the claim sentence contains a number the snapshot never prints, neither as digits nor, for 0 to 12, as the English word. Usually this is a sum, a percentage or a year the extractor derived. A claim may rightly cite a figure from a second source, so a warning is a prompt to read again.

#### What it does not check

- Whether a claim says what its source says. A quote can exist in the snapshot and still not support the claim. That needs a second reader.
- `kb/core.json` and `kb/harness.json`. Tests check them (sections 3.3 and 3.4).
- That every source has claims, or that every source has a lock entry.
- The contents of `kb/snapshots-prev/`.

#### Exit codes

| Code | Meaning |
|---|---|
| 0 | Every claim was checked and the data files are well formed. |
| 1 | Something is wrong with the data: a claim with a missing, mistyped or invalid field, a duplicate id, an unknown source, a quote that is not in its snapshot, a snapshot that differs from the lock, or a malformed `sources.json`, lock or `pending.json`. |
| 2 | Misuse: bad arguments, or a file argument that does not exist. |
| 3 | Cannot check: a snapshot is absent and nothing else is wrong. "Cannot check" is not "passed". Run `kb_update.py --apply` or `kb_fetch.py` first. |

Precedence: 2, then 1, then 3, then 0.

### 2.4 `scripts/kb_fetch.py`

Downloads the sources listed in `kb/sources.json` into `kb/snapshots/`. It is for bootstrap and recovery. The routine refresh is `kb_update.py --apply`. It uses the network for sources with a `url` and writes files under `kb/`.

Network behavior: GET only, a fixed generic User-Agent (`kb-fetch/1.0 (documentation snapshot)`), a per-request timeout, and a cap on response size (values in section 4). A redirect is followed only to a host that appears among the `url` values in `kb/sources.json` (for `--list`, the host of the URL given) and never from https to http. Nothing about the machine or the review is sent, though a server sees the connection's address.

If a response body starts with `<!doctype` or `<html`, it is reduced to its readable text (script, style, noscript, svg, nav, footer and header content is dropped) before it is hashed and stored.

A `path` source is read relative to the repository root, not the current directory, unless it is absolute. A `bundled` source is read from `--bundled-dir`.

All downloads happen before anything is written, so a failure while downloading leaves the files as they were. Files are written to a temporary file in the same folder and then moved into place.

| Option | Argument | Default | Meaning |
|---|---|---|---|
| `--only` | `ID[,ID...]` | all sources | Fetch only these source ids. An unknown id exits 2. |
| `--bundled-dir` | `DIR` | none | Directory of the `claude-api` skill bundled with Claude Code, for sources marked `bundled`. Without it, those sources fail. |
| `--list` | `URL` | none | Print the URL's body to stdout and write nothing. Used to discover index pages. When given, no source is fetched. |

What a run does for each selected source:

- Hash equals the lock entry and the local snapshot matches: counted as unchanged.
- Hash equals the lock entry but the local snapshot is missing or differs: the snapshot is rewritten from the download (restored).
- Hash differs, or the source has no lock entry: the snapshot and the lock entry are written. If the source already had a lock entry, its id is also recorded in `kb/pending.json`, and the previous snapshot is copied to `kb/snapshots-prev/<id>.md` if the local file existed and matched the lock. A source with no lock entry is new and is not pending.
- Download failed: reported, the other sources are still written, and the failed source keeps its lock entry.

Text output: `changed=N unchanged=N restored=N failed=N`, then one line per changed (`+`), restored (`=`) and failed (`!`) source. A line lists any source with no previous snapshot to diff against; read those whole. There is no JSON mode.

| Code | Meaning |
|---|---|
| 0 | Every selected source was read. |
| 1 | Some source could not be read, or `--list` could not read its URL. |
| 2 | Misuse: an unknown `--only` id, a missing or unreadable `kb/sources.json`, a `sources.json` that is not a list, or bad arguments. |

### 2.5 `scripts/kb_update.py`

Says what changed in the documentation since the last update and what it affects. It downloads every source that has a `url`, plus the two documentation indexes (`INDEXES` in the script), and compares them with the locks. By default it writes nothing inside the repository, so it runs from a read-only installed copy. With `--apply` it writes under `kb/`.

Network behavior: GET only, to the hosts of the `url` values in `kb/sources.json` and of the indexes, with the User-Agent, per-request timeout and size cap of `kb_fetch.py`, and an overall time budget (section 4). A redirect to any other host is refused. No review data, claim, setup or local path is sent. Reading a `bundled` or `path` file is local.

Usage:

```
kb_update.py [--json] [--out FILE] [--apply [--partial]] [--only ID[,ID...]] [--bundled-dir DIR] [--max-seconds N]
kb_update.py --reviewed ID[,ID...]|all
```

Run it as `python -B` to avoid writing bytecode. The script also sets that flag itself before importing `kb_fetch`.

| Option | Argument | Default | Meaning |
|---|---|---|---|
| `--json` | none | off | Print the report as one JSON object instead of text. |
| `--out` | `FILE` | none | Also write the JSON report here. Must be outside the repository directory (exit 2 otherwise). |
| `--apply` | none | off | Write changed snapshots, `pending.json` and the locks. Working clone only. Nothing is applied if a source failed, unless `--partial`. Does not run the gate; it prints `next: python scripts/kb_gate.py`. |
| `--partial` | none | off | With `--apply`, apply what downloaded even if some source failed. Without `--apply` it exits 2. |
| `--reviewed` | `ID[,ID...]` or `all` | none | Take source ids or page URLs off `pending.json`. Takes no other option. |
| `--only` | `ID[,ID...]` | all sources | Compare only these source ids. The indexes are then not checked, and pending page lists are left out of the report. |
| `--bundled-dir` | `DIR` | none | Directory of the `claude-api` skill. Needed to compare `bundled` and `path` sources; without it they are reported under `not_checked` and counted in `not_compared`. |
| `--max-seconds` | `N` | 600 | Time budget for all downloads. A source or index not started in time is reported as failed. `0` means the default. |

#### Modes

- Check (default): compares and reports. Writes nothing in the repository.
- `--apply`: the same comparison, then writes. It requires a working clone: `kb/` writable, a `.git` entry at the repository root, and a path not under `plugins/cache`. Otherwise exit 2.
- `--apply --partial`: as `--apply`, but applies even if a source failed.
- `--reviewed`: its own step. It runs the gate first and refuses unless the gate reports no errors and every snapshot to release exists. Then it removes the named items from `pending.json` and prints `pending left: N`. It sends nothing over the network. Combined with `--apply`, `--partial`, `--json`, `--out`, `--only`, `--bundled-dir` or `--max-seconds` it exits 2.

#### Two baselines

The lock (`snapshots.lock.json`) records what was last downloaded. `pending.json` records what was downloaded but not yet re-read. An update that stops halfway keeps flagging its claims, because pending items count as work even when today's bytes match the lock.

`--apply` writes in this order, each file by temporary file and replace: `pending.json`, then the previous snapshot of each changed source in `kb/snapshots-prev/<id>.md` (only if the local file matches the lock), then the snapshots, then `index.lock.json`, and `snapshots.lock.json` last. A source with no lock entry is new and is not pending.

An index is not accepted as the new baseline if it parses into no URLs, or into fewer than half of the baseline's URLs. It is listed as failed. An index with no baseline is recorded by `--apply` and listed under `no_index_baseline`.

#### Report keys (JSON, `schema_version` 1)

Only a run that gets as far as comparing emits a report. `--reviewed`, a usage error, and a selection that compared nothing print a one-line message and no JSON.

| Key | Type and shape | Meaning |
|---|---|---|
| `schema_version` | integer, 1 | |
| `lock_oldest`, `lock_newest` | `YYYY-MM-DD` or null | Fetch dates (UTC) of the oldest and newest snapshot in the lock. Not review dates. Null when the lock is empty. |
| `changed_sources` | list of `{id, url, claims, core_or_harness_ids, new}` | Downloaded hash differs from the lock. `url` holds the source label (url, path or `bundled:<path>`). `claims` is the number of claims citing it. `core_or_harness_ids` are those claim ids that `core.json` or `harness.json` depend on. `new` is true when the source has no lock entry. |
| `pending` | `{sources: [{id, since, claims, core_or_harness_ids}], new_pages: [{url, since}], removed_pages: [{url, since}]}` | Fetched earlier and not yet released by `--reviewed`. With `--only`, page lists are empty and sources are filtered. |
| `unchanged` | list of source ids | Hash equals the lock. |
| `failed` | list of `{id, error}` | A source id or an index URL, with the error text. |
| `not_checked` | list of `{id, reason}` | Sources skipped, with the reason. |
| `not_compared` | `{sources, claims}`, integers | Bundled or local sources skipped for want of `--bundled-dir`, and the claims that rest on them. |
| `new_pages`, `removed_pages` | list of `{index, url}` | Index links added or removed since the baseline. |
| `no_index_baseline` | list of index URLs | Indexes with no entry in `index.lock.json`. |
| `snapshot_mismatch` | list of source ids | The download equals the lock but the local snapshot's hash does not. Under `--apply` it is restored. |
| `unreadable_claim_lines` | integer | Claim lines that could not be read, so impact counts are low. |
| `incomplete` | list of strings | Why the comparison was not complete. |
| `compared` | integer | Sources and indexes actually compared. |
| `restored_snapshots` | list of source ids | Set by `--apply`. Snapshots that were missing or altered, rewritten. Empty otherwise. |
| `no_previous` | list of source ids | Set by `--apply`. Changed sources whose previous snapshot could not be kept because the local file was absent or did not match the lock. Read these sources whole; there is no diff. Empty otherwise. |
| `applied` | boolean | True when `--apply` wrote files. False when not requested, or when it was refused because a source failed and `--partial` was not given. |
| `exit` | integer | The exit code. |

The text report shows at most 40 page URLs per list and says how many more exist. `--json` shows all.

#### Exit codes

| Code | Meaning |
|---|---|
| 0 | The declared scope was compared completely, and nothing changed or is pending. |
| 1 | A download failed and nothing could be compared. |
| 2 | Misuse, decided before any request or after finding nothing to compare: `--apply` or `--reviewed` outside a working clone; an unknown `--only` id; `--out` inside the repository; `--partial` without `--apply`; `--reviewed` with another option; `--reviewed` of an item that is not pending, while the gate fails, or when a snapshot to release is absent; a selection that compared nothing and failed nothing. |
| 3 | There is work: a changed source, a new or removed page, or a pending item. A removed page alone is work. |
| 4 | Nothing changed was seen but the comparison was incomplete: a download failed, an index has no baseline, a local snapshot differs from the lock, or a claim line was unreadable. |

Precedence: 2, 1, 3, 4, 0. A partial failure shows in the report and, when work is present, stays exit 3. Failed sources keep their lock entry.

Known limits: two updates run at once are not locked against each other. An HTML source is hashed after its text is extracted, so a changed link target under identical text hashes identically. The index comparison sees absolute markdown link targets only, not changed descriptions.

### 2.6 `evals/build_fixtures.py` and `evals/build_process_fixtures.py`

Both build throwaway directories for calibrating a review. They use neither the network nor `kb/`. Nothing they write is executed by the review.

- `build_fixtures.py` builds two Claude Code setups for the setup review. `planted/` has ten defects, each documented in `evals/ANSWER-KEY.md`. `clean/` has nothing wrong that matters. Each folder holds `home/.claude` and `project`. Session history is generated with the time of the build, so it falls inside the default measurement window.
- `build_process_fixtures.py` builds two orchestration processes for the process review. `process-planted/` has ten defects and four things that are deliberately sound. `process-clean/` is built to give a reviewer nothing to find that is a defect by the guide's standard; it is not proven defect-free, and its answer key records one open finding. Records are made by a seeded generator (seed `20261127`), so generated files are identical on every run.

Usage for both: `python evals/<script>.py <output dir>`

| Argument | Meaning |
|---|---|
| `<output dir>` | Exactly one argument. The two folders are created inside it. |

There are no options. An argument starting with `-` (including `--help`) is treated as misuse: the script prints its docstring to stderr and exits 2.

Use a new, empty output directory. The named folders are overwritten file by file, and a file left from an earlier build that this build does not write stays in place.

| Script | Creates |
|---|---|
| `build_fixtures.py` | `<output dir>/planted`, `<output dir>/clean` |
| `build_process_fixtures.py` | `<output dir>/process-planted`, `<output dir>/process-clean` |

Both print `built <path> and <path>` on success.

| Code | Meaning |
|---|---|
| 0 | Both folders were built. |
| 1 | A write failed. The script raises and exits with a traceback. |
| 2 | The arguments are not exactly one directory. |

## 3. Data files

All files are under `kb/`. JSON files are UTF-8. Files written by `kb_fetch.py` and `kb_update.py` use two-space indentation and sorted keys.

| File | Committed | Written by |
|---|---|---|
| `kb/claims/*.jsonl` | yes | people or agents (see `kb/EXTRACTION.md`) |
| `kb/sources.json` | yes | people |
| `kb/core.json` | yes | people |
| `kb/harness.json` | yes | people |
| `kb/snapshots.lock.json` | yes | `kb_fetch.py`, `kb_update.py --apply` |
| `kb/index.lock.json` | yes | `kb_update.py --apply` |
| `kb/pending.json` | not git-ignored; absent from the repository at present | `kb_fetch.py`, `kb_update.py` |
| `kb/snapshots/` | no, git-ignored | `kb_fetch.py`, `kb_update.py --apply` |
| `kb/snapshots-prev/` | no, git-ignored | `kb_fetch.py`, `kb_update.py --apply` |

### 3.1 `kb/claims/*.jsonl`

One JSON object per line. Blank lines are ignored. A file name is free; each file holds claims from one or more topics. `kb.py`, `kb_gate.py` and `kb_update.py` read every `*.jsonl` in the folder.

Example (one line, from `kb/claims/skills-plugins.jsonl`):

```json
{"id": "skills-001", "topic": "skills", "kind": "fact", "applies_to": ["claude-code"], "claim": "By default, Claude Code truncates each skill’s combined `description` and `when_to_use` at 1,536 characters in the skill listing.", "why": "Claude Code caps listing text to reduce context usage.", "check": "Check that the key use case comes first and fits within `skillListingMaxDescChars`, which is configurable.", "quote": "the combined `description` and `when_to_use` text is truncated at 1,536 characters in the skill listing to reduce context usage", "source": "cc-skills"}
```

All nine fields are required and non-empty.

| Field | Type | Allowed values and meaning |
|---|---|---|
| `id` | string | `<prefix>-<number>`: one or more lower-case segments separated by hyphens, starting with a letter, then hyphen and digits (regular expression `^[a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*-\d+$`). Examples: `hooks-012`, `skills-802`. Unique across all of `kb/claims/`, including files not being checked. The prefix is a namespace; `topic` is what queries select on. |
| `topic` | string | One of `prompting`, `model`, `context`, `cost`, `skills`, `subagents`, `hooks`, `mcp`, `plugins`, `settings`, `orchestration`, `tools`, `evals`, `harness`. |
| `kind` | string | `fact` (how the harness or API behaves), `behavior` (how a model behaves), `practice` (what Anthropic recommends). |
| `applies_to` | list of strings, non-empty | Each item is `all`, `claude-code`, or a model id such as `claude-opus-5-5`, optionally ending in `-YYYYMMDD`. Regular expression for a model id: `claude-[a-z]+-\d+(-\d{1,2})?(-\d{8})?`. An alias and its dated id are two different strings; nothing resolves one to the other. |
| `claim` | string | One sentence that stands on its own. |
| `why` | string | The reason the source gives, in one sentence. |
| `check` | string | What an auditor would look at in a real setup because of this claim. |
| `quote` | string | A span copied character for character from the snapshot. After normalization it is 25 to 400 characters and holds at least 18 letters or digits. |
| `source` | string | A source id from `kb/sources.json`. It is the snapshot file name without `.md`. |

Validated by: `kb_gate.py` checks every row of the table above, that the quote is in the snapshot, and that ids are unique. `kb.py` checks only that each line is a JSON object with all nine keys, and fails with exit 3 otherwise. `tests/test_instrument.py` checks that ids are unique, topics are valid and sources exist, without needing the snapshots. Not checked by any script: that the claim says what the quote says, that `why` and `check` are accurate, or that a number in `claim` was printed by the source (the gate only warns about that last case).

### 3.2 `kb/sources.json`

A JSON list. Each entry describes one source.

Examples (the first and one `bundled` entry, from the file):

```json
{
  "id": "cc-how-claude-code-works",
  "url": "https://code.claude.com/docs/en/how-claude-code-works.md",
  "tier": 1,
  "topic": "harness"
},
{
  "id": "bd-prompt-audit",
  "bundled": "shared/prompt-audit.md",
  "tier": 1,
  "topic": "prompting"
}
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Lower-case letters, digits and hyphens, starting with a letter or digit. Unique. It names the snapshot file `kb/snapshots/<id>.md`. |
| `url` or `bundled` or `path` | string | Exactly one of the three. The locator, see below. |
| `tier` | integer | 1, 2 or 3. A boolean or a string is rejected. |
| `topic` | non-empty string | A free label. It is not checked against the claim topics. |

Locators:

| Locator | Value | How it is read |
|---|---|---|
| `url` | An `http://` or `https://` address | Downloaded by `kb_fetch.py` and `kb_update.py`. Redirects only to hosts that appear among all `url` values. |
| `bundled` | A path relative to the `claude-api` skill directory bundled with Claude Code | Read from `--bundled-dir`. Without that option the source cannot be fetched or compared. |
| `path` | A file path, relative to the repository root or absolute (`~` is expanded) | Read from disk. `kb_fetch.py` needs no extra option. `kb_update.py` reports it under `not_checked` unless `--bundled-dir` is given. No entry in the current file uses it. |

The code only requires that `tier` is 1, 2 or 3. It does not give the tiers a behavior of their own.

Validated by: `kb_gate.py` (shape, unique ids, exactly one locator, locator is a non-empty string, `url` begins with `http://` or `https://`, tier value, topic present). `kb_fetch.py` and `kb_update.py` assume a valid file. Not checked: that the URL resolves, or that the topic matches anything.

### 3.3 `kb/core.json`

A JSON object. Each key is a review question. Each value is an object with two fields. `kb.py core` lists the questions and prints the core claims of one.

Question names in the file: `placement`, `feedback`, `economy`, `routing`, `allocation`, `skill`, `subagent`, `instructions`, `hooks`, `prompting`.

| Field | Type | Meaning |
|---|---|---|
| `principle` | string | The short first read for that question. |
| `claims` | list of claim ids | The core claims, in print order. |

Example (the start of `placement`):

```json
"placement": {
  "principle": "A rule that must always hold belongs in a hook or a permission rule, because an instruction in CLAUDE.md or a skill is a request and not a guarantee. ...",
  "claims": [
    "harness-002",
    "harness-003",
```

Validated by: `tests/test_instrument.py` (`RepositoryKnowledgeBaseTest`): each `principle` is non-empty, each question lists at most 14 claims, each id exists, and each claim applies to `all` or `claude-code` (not tied to one model). `kb.py core` exits 3 if a listed id does not exist. `kb_update.py` reads the ids to flag changed sources that core claims depend on (`core_or_harness_ids`). `kb_gate.py` does not read this file.

### 3.4 `kb/harness.json`

A JSON object of numbers about Claude Code that `scripts/measure.py` depends on. `measure.py` reads it when it starts, so the file must exist and be valid. A key starting with `_` is a note.

Each other key is an object:

| Field | Type | Meaning |
|---|---|---|
| `value` | number | The number `measure.py` uses. |
| `claim` | string | The id of the claim that documents it. |
| `stated_as` | string | The text of the number as the claim's quote prints it. |

Keys and what `measure.py` calls them:

| Key | Value | Constant in `measure.py` |
|---|---|---|
| `skill_listing_cap_chars` | 1536 | `LISTING_CAP` |
| `instruction_import_max_hops` | 4 | `IMPORT_DEPTH` |
| `instruction_file_recommended_max_lines` | 200 | `LONG_FILE_LINES` |
| `cache_lifetime_seconds_short` | 300 | `CACHE_SHORT` |
| `cache_lifetime_seconds_long` | 3600 | `CACHE_LONG` |

Example:

```json
"skill_listing_cap_chars": {
  "value": 1536,
  "claim": "skills-001",
  "stated_as": "1,536"
}
```

When the documentation changes, the gate flags the claim, and the number is corrected here, not in the script.

Validated by: `tests/test_instrument.py`: for each key not starting with `_`, the claim id exists and `stated_as` occurs in that claim's quote. Not checked: that `value` agrees with `stated_as`. `kb_gate.py` does not read this file. `kb_update.py` reads the `claim` fields to flag changed sources.

### 3.5 `kb/snapshots.lock.json`

A JSON object keyed by source id. It records what was last downloaded. `kb_fetch.py` and `kb_update.py --apply` write it, last of all their writes.

| Field | Type | Meaning |
|---|---|---|
| `sha256` | string, 64 lower-case hex digits | Hash of the stored snapshot bytes. For an HTML page, the hash of the extracted text. |
| `bytes` | integer, 0 or more | Size of the stored snapshot. |
| `fetched` | string, `YYYY-MM-DD` (UTC) | The date it was downloaded. |
| `source` | string | The locator as a label: the URL, the path, or `bundled:<path>`. |

Example:

```json
"bd-agent-design": {
  "bytes": 8837,
  "fetched": "2026-11-14",
  "sha256": "b179ea16233b16f53a3d8f6ed58465464050142de80dedcc9e453b672d06a201",
  "source": "bundled:shared/agent-design.md"
}
```

Validated by: `kb_gate.py` checks the field shapes above, that each key is a source in `sources.json`, and (for sources whose snapshot is present) that the snapshot's SHA-256 equals `sha256`. It does not check `bytes` against the file, or that `source` matches `sources.json`, or that every source has an entry.

### 3.6 `kb/index.lock.json`

A JSON object. Each key is the URL of a documentation index (the `INDEXES` in `kb_update.py`). Each value is a sorted list of the absolute URLs of markdown links found in that index. `kb_update.py` compares a fresh download with this list to find new and removed pages.

Example (the start of the first entry):

```json
{
  "https://code.claude.com/docs/llms.txt": [
    "https://code.claude.com/docs/_llms/de.txt",
    "https://code.claude.com/docs/_llms/es.txt",
```

Validated by: `kb_gate.py` checks only that the file maps each string key to a list of strings. It does not check that the URLs are reachable or that the keys are the current `INDEXES`.

### 3.7 `kb/pending.json`

A JSON object recording what was downloaded but not yet re-read. It does not exist in the repository now. `kb_fetch.py` and `kb_update.py --apply` create it when a source that already had a lock entry changes, or when an index gains or loses a page. `kb_update.py --reviewed` removes items. `kb.py` reads it to annotate claims. An item added earlier keeps its older date.

Shape (placeholders, not a real file):

```json
{
  "sources": {"<source id>": "YYYY-MM-DD"},
  "new_pages": {"<page url>": "YYYY-MM-DD"},
  "removed_pages": {"<page url>": "YYYY-MM-DD"}
}
```

Each date is the UTC day the item was first recorded. Readers treat a missing key as empty.

Validated by: `kb_gate.py`: the file is an object with only the keys `sources`, `new_pages` and `removed_pages`; each maps strings to `YYYY-MM-DD` dates; each id under `sources` is a source in `sources.json`. Not checked: that a pending source has a snapshot (the `--reviewed` step checks that), or that a page URL belongs to an index.

### 3.8 `kb/snapshots/` and `kb/snapshots-prev/`

Both are git-ignored, because the snapshots are third-party documentation fetched locally.

- `kb/snapshots/<source id>.md` holds the raw text of each source as last downloaded. It is the text that quotes are matched against. Create it with `kb_update.py --apply` or `kb_fetch.py`. Without it the gate exits 3.
- `kb/snapshots-prev/<source id>.md` holds the snapshot from before the last change, kept only when the local file matched the lock at that moment. A source already pending keeps its older copy, so a diff runs against what was last reviewed. When no usable previous snapshot exists, an old copy is deleted and the id is reported as `no_previous`. No script reads this folder. It exists so a reviewer can diff the old snapshot against the new.

Validated by: the gate reads `kb/snapshots/` (presence, hash against the lock, quote matches). Nothing reads or checks `kb/snapshots-prev/`.

## 4. Limits fixed in code

None of these has a flag unless the last column says so. To change one, edit the constant.

| Value | Constant | File | Changed by a flag |
|---|---|---|---|
| 60 seconds, per request | `TIMEOUT` | `scripts/kb_fetch.py` | no |
| 5,000,000 bytes, per response (a larger one is refused) | `MAX_BYTES` | `scripts/kb_fetch.py` | no |
| 600 seconds, total for all downloads in one run; checked before each download starts | `MAX_SECONDS` | `scripts/kb_update.py` | yes, `--max-seconds` (0 means 600) |
| Index accepted only if it parses into at least one URL and at least half the baseline's URLs | inline in `check()` | `scripts/kb_update.py` | no |
| The two indexes checked | `INDEXES` | `scripts/kb_update.py` | no (skipped with `--only`) |
| 40 page URLs per list in the text report | `SHOW` | `scripts/kb_update.py` | no (`--json` shows all) |
| 25 to 400 characters, quote length after normalization | `MIN_QUOTE`, `MAX_QUOTE` | `scripts/kb_gate.py` | no |
| 18 letters or digits in a quote | `MIN_ALNUM_CHARS` | `scripts/kb_gate.py` | no |
| 30 days of history | `DEFAULT_DAYS` | `scripts/measure.py` | yes, `--days` |
| 36500 days, largest `--days` | `MAX_DAYS` | `scripts/measure.py` | no |
| 4 characters per token | `CHARS_PER_TOKEN` | `scripts/measure.py` | no |
| 15 description pairs listed | `TOP_OVERLAPS` | `scripts/measure.py` | no |
| 0.2 Jaccard, lowest listed overlap | `OVERLAP_MIN_JACCARD` | `scripts/measure.py` | no |
| 5 distinctive words, minimum for a description to be compared | `OVERLAP_MIN_WORDS` | `scripts/measure.py` | no |
| 4 characters, shortest word counted | `OVERLAP_MIN_WORD_CHARS` | `scripts/measure.py` | no |
| One third, a word in more descriptions than this share is ignored | `OVERLAP_COMMON_SHARE` | `scripts/measure.py` | no |
| 6 descriptions, the common-word filter applies from here | `OVERLAP_COMMON_MIN_PIECES` | `scripts/measure.py` | no |
| 12 shared words listed per pair | `OVERLAP_SHARED_SHOWN` | `scripts/measure.py` | no |
| 12 tools listed in `usage.tool_result_chars` | `TOP_TOOL_RESULTS` | `scripts/measure.py` | no |
| 2000 characters, longest frontmatter value kept | `MAX_VALUE` | `scripts/measure.py` | no |
| 200 characters, longest settings or hook scalar kept | `MAX_SCALAR` | `scripts/measure.py` | no |
| 200 characters, longest permission rule kept | `MAX_RULE` | `scripts/measure.py` | no |
| 200 permission rules kept per list | `MAX_RULES` | `scripts/measure.py` | no |
| 80 characters, longest model, tool, skill or agent name kept from history | `NAME_MAX` | `scripts/measure.py` | no |
| 0.5, a cache rebuild writes more than this share of its prompt | `REBUILD_SHARE` | `scripts/measure.py` | no |
| 0.5, a prompt under this share of the previous one reads as compaction | `COMPACTION_SHRINK` | `scripts/measure.py` | no |
| 65536 bytes, tail of a transcript read to see whether the file lies before the window | `TAIL_BYTES` | `scripts/measure.py` | no |
| 50 paths listed under `read_scope.skipped_outside_scope` | `SKIPPED_SHOWN` | `scripts/measure.py` | no |

Numbers about Claude Code itself live in `kb/harness.json`, not in the scripts, and change by editing that file: skill listing cap 1536 characters, import depth 4 hops, recommended instruction file length 200 lines, cache lifetimes 300 and 3600 seconds. The skill listing cap is also overridden in a measured setup by a positive integer `skillListingMaxDescChars` in its settings, and `skill_listing_cap.source` says which applied.
