# Capabilities a setup may leave unused

Question 7 of the setup review. The first six questions find what is wrong
with the pieces a setup has; this guide is for what it does not have. People
often build in prose what Claude Code already does as a feature, and the
prose does it worse: a rule in capitals where a permission rule would hold
it, "remember to run the tests" where a Stop hook would run them.

## How to use it

Start from the setup, not from this list. For each row, look for its signal
in the measurement, the files and the session history. **A row applies only
when its signal is there, and the finding names the signal.** A capability
the setup does not use is not a finding: most setups need few of these, and a
review that recommends every feature teaches the person nothing about theirs.

The measurement's `features` block says what is configured: hooks by event
and whether they block on failure, permission rules by kind, path-scoped
rules, which agents set `model`, `effort` and `tools`, which skills set
invocation flags, MCP servers, enabled plugins, and whether `outputStyle` and
`statusLine` are set. What it marks `not_measured` (auto memory, checkpoints,
how the person runs sessions) you learn from the history or by asking.

The "what it buys" and "does not fit" columns rest on the claims in the last
column; read their quotes with `kb.py cite` before citing them. The "fits
when" signals are this guide's judgment, marked *(inference)*: the
documentation says what a feature does, not when a given person needs it.
Say so in the finding. Ids shown as "see X" are related claims whose quotes
were not checked for that cell; read them before relying on them.

Versions matter here more than elsewhere. Several rows name the Claude Code
version a feature needs; when the setup's version is unknown, say the change
needs that version or later.

## The capabilities

| # | Capability | What it buys | Fits when (observable signal) | Does not fit when | Claims |
|---|---|---|---|---|---|
| 1 | Path-scoped rules (`.claude/rules/*.md` with `paths:`) | Guidance for one language or directory loads only when Claude works on matching files, keeping CLAUDE.md small | CLAUDE.md is over 200 lines or has sections about a single subsystem or language *(inference)*; harness-001 gives 200 lines as the threshold | The rule must hold in every session: path-scoped rules are summarized away at compaction (context-005), so a must-always rule belongs unscoped or in root CLAUDE.md | harness-021, context-005 |
| 2 | Stop / SubagentStop hooks as completion checks | A deterministic check that can keep the turn going before "done" | Instruction text says "run tests before finishing" / "always verify" and session history shows turns ending with no test run *(inference)*; long unattended runs (harness-064) | The check needs more than 8 consecutive blocks without raising the cap (hooks-014); a script that returns `continue: false` ends the turn instead of continuing it (hooks-002); the check is one-off judgment better done by a prompt or a fresh-subagent review *(inference)* | hooks-014, hooks-002 |
| 3 | PreToolUse hook as a blocking guard (exit 2) | Block a tool call before permission rules are evaluated, in every mode | A prose rule like "never touch X" that must hold and needs inspection of the full command, not just a pattern a permission rule can express *(inference)*; settings-021 | A plain path/command pattern is enough: use a deny rule (row 5). A matcher on Edit/Write does not stop edits made through shell commands (hooks-034) | settings-021, hooks-029 |
| 4 | `onFailure: "block"` on command/http/mcp_tool hooks | A policy hook that crashes or times out blocks the action instead of letting everything through | A PreToolUse/policy hook exists and the files show a script path or interpreter that could be missing *(inference)*; needs v2.1.295+ (v2.1.328+ for mcp_tool) | The hook is on Stop, SubagentStop, TaskCompleted or TeammateIdle: the option is ignored there (sdk-060, documented for the SDK; see contradiction list). PostToolUse cannot block, the tool already ran | hooks-005, sdk-060 |
| 5 | Permission rules (deny / ask) in place of prose rules | Enforcement by Claude Code, not by the model; deny holds in every mode | CLAUDE.md or skills contain "never read .env / never run X / never push" lines with no matching `permissions.deny` or `ask` entry *(inference)* | The thing to block is reached by a shell subprocess: Read/Edit deny rules miss indirect shell access (settings-020, see harness-030); use sandbox or a hook. Bash patterns match normalized text, so variants may slip through (settings-019) | settings-017, harness-029 |
| 6 | Permission modes (auto, dontAsk) | Auto: fewer prompts with a classifier. dontAsk: predefined allowlist for CI | Session history shows many manual approvals of the same commands (inference; mods-023 reports 93% of manual prompts accepted, not cited as quote); CI/restricted runs with no allowlist | Irreversible actions where one mistake costs more than reviewing each (see contain-020); `auto` and `bypassPermissions` as defaultMode are ignored from project or local settings (see settings-003) | settings-023, settings-026 |
| 7 | `disable-model-invocation: true` (and `user-invocable: false` for the reverse) | Skill with side effects runs only when the user calls it; `user-invocable: false` hides a skill from the user while Claude can still use it | A skill whose body does deploy / commit / push / delete / send and has no flag, so Claude can start it on its own *(inference)* | The skill is read-only or should auto-trigger. Also: a skill with this flag cannot be preloaded into a subagent (see subagents-017) | skills-009, skills-011 |
| 8 | Skills bundling scripts | Deterministic work runs as a script instead of being re-derived each time; `${CLAUDE_SKILL_DIR}` plus a matching Bash rule avoids a prompt | A skill or CLAUDE.md block spells out a long fragile command sequence in prose that is repeated across sessions *(inference)* | The task is open-ended judgment: exact scripts for judgment calls are a finding (see prompting-044) | skills-059, skills-038 |
| 9 | Skill `context: fork` | Skill runs in a new subagent without the conversation history | A skill with long verbose output the main session does not need again (inference; subagents-028) | The skill is only guidelines with no task (skills-020: returns no meaningful output); the body relies on conversation history | skills-019 |
| 10 | Subagent `model` | Cheaper model for work where mistakes are cheap to spot | Many Explore/search-style subagent runs on the session's top model (inference; check `/usage` by subagent) | Code edits and judgment calls (see verif-065). Note: the built-in Explore no longer uses Haiku, so "we use Explore" does not mean it is cheap | verif-066, subagents-007 |
| 11 | Subagent `effort` (field or per-invocation) | Lower or higher reasoning for a role independent of the session | A custom subagent whose definition has no `effort` and whose task is clearly routine or clearly hard *(inference)* | The subagent is a fork, forked skill or teammate (different resolution order, subagents-033); the model differs from the main one, where session effort does not apply (see model-261) | subagents-032, subagents-033 |
| 12 | Subagent `tools` (allowlist) | Narrow tool access for security and focus | Subagent files with no `tools` line: they inherit everything including MCP tools (subagents-004). This one is directly measurable | A role that truly needs broad tools. Note `disallowedTools: Bash(git push *)` removes all of Bash, not just that command (see subagents-006) | subagents-038, subagents-004 |
| 13 | Subagent isolation: `isolation: worktree`, background | Isolated repository copy; side work running in the background | Parallel subagents or agents editing the same files, or session logs showing edit collisions *(inference)* | Read-only research subagents. Agent teams do not isolate teammates in worktrees (see orchestration-005); background subagents lose some tools (see subagents-023/024) | subagents-043, subagents-022 |
| 14 | MCP scoping (inline `mcpServers` in a subagent; tool search) | Keeps an MCP server's tool descriptions out of the main conversation; tool search defers definitions | `.mcp.json` lists servers used by only one role, or `/context` shows large MCP tool definitions *(inference)*; cost-051 gives about 10K tokens of schemas as a threshold, not cited | Server needed every turn: use `alwaysLoad` (see mcp-004); plugin agents ignore `mcpServers` (see subagents-018); tool search is already on by default (mcp-001) so recommending it for a default setup is empty | subagents-041, mcp-001 |
| 15 | Output styles | A consistent role/tone/format across every response | Repeated format or tone instructions copied across many prompts or CLAUDE.md *(inference)* | You need enforcement: "nothing enforces it". Subagents do not follow the style. A custom style drops built-in coding instructions unless `keep-coding-instructions: true` (see skills-070) | skills-069, skills-072 |
| 16 | Status line | Free, local view of context, cost, cache read/creation | The user complains of cost or of sessions growing, with no status line configured *(inference)*; can show `cache_creation_input_tokens` | Cost shown is a local list-price estimate and resets on `/clear` (see cost-806), so not a bill | cost-805, cost-022 |
| 17 | Auto memory | Cross-session notes loaded from MEMORY.md (first 200 lines or 25 KB) | The user repeats the same preferences in every session, visible in history *(inference)*; what it buys is inference, the quote only covers loading | Multi-tenant SDK use: Anthropic advises `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` (see sdk-115); poisoned memory can persist (see contain-037). KB has no Claude Code quote on its benefit, weak row | context-011 |
| 18 | Compaction settings (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, Compact Instructions, `/compact` focus) | Control when compaction triggers and what survives | History shows corrections or early instructions lost after compaction (quote: early detail "may be lost"); steering via Compact Instructions or `/compact` focus is from the claim text, not the quote *(inference)* | One huge file/tool output refills context, which compaction cannot fix (see context-802); persistent rules belong in CLAUDE.md. `/clear` costs nothing and is cheaper when continuity is not needed (see cost-045) | context-801, cost-807 |
| 19 | `/context` | Live per-category breakdown, shows loaded CLAUDE.md and memory files | First step when a setup reports "context fills fast" or has many instruction files, skills, MCP servers *(inference)* | Not a fix by itself, it diagnoses | harness-055, context-007 |
| 20 | `/usage` | Breakdown by skill, subagent, plugin, MCP server; flags patterns at 10% of usage | User asks "where does my usage go"; plans of type Pro/Max/Ultra/Team/Enterprise only (cost-028 scope) | API-key users on other plan types (inference from the plan list); figures are local estimates (see cost-027) | cost-804, cost-028 |
| 21 | `/doctor prompt-audit` and `/skill-doctor` | Finds stale instructions, missing references, contradictions; lists skills never invoked | Instruction files older than the current models, or with contradictions the reviewer already sees *(inference)*; many skills with none ever invoked | `/doctor prompt-audit` needs v2.1.283+; `/skill-doctor` needs the feature-flag fetch on v2.1.252+ (see skills-805). It proposes edits and changes nothing until asked | harness-057, skills-040 |
| 22 | Headless `claude -p` / Agent SDK, `--bare`, budget caps | Unattended runs in scripts and CI | Repeated manual, identical tasks (lint fix, diff review) with the same prompt in history *(inference)*; sdk-033 names CI lint/review as a fit | No allow rules: `-p` starts in Manual and denies calls needing approval (settings-024). `--max-budget-usd` can be overshot (sdk-017) | settings-024, orchestration-023 |
| 23 | Plugins and marketplaces | One installable unit of skills, agents, hooks, MCP servers shared across teammates or projects | The same `.claude/` files are copied between repos or people *(inference)* | Solo, single-repo setup. Each enabled plugin adds names and descriptions to context on every turn (plugins-003); `claude plugin details` estimates this | plugins-002, plugins-003 |
| 24 | Checkpoints / `/rewind` | Abandon a bad path and restore files and a cached prefix | History shows long sessions with several failed corrections in a row *(inference)*; harness-054 recommends `/clear` plus a better prompt after two failed corrections | Changes made outside Claude's tracking (shell edits to untracked files); only the 100 most recent checkpoints are kept (harness-049) | harness-049, cost-012 |
| 25 | Sandbox (shell) | Fewer permission prompts: Anthropic internal figure of an 84% reduction | Frequent prompts for shell commands in history, and a platform that supports it *(inference)* | Off by default and covers shell commands only: file tools, MCP servers and hooks run outside it. Not on native Windows (see contain-007) | contain-022, settings-027 |

## Facts that surprise people

These are documented, and each contradicts a common belief. Check for the
belief in the setup before recommending around it.

- `onFailure: "block"` is ignored on Stop, SubagentStop, TaskCompleted and
  TeammateIdle: a completion-check hook that crashes does not block (sdk-060).
- From v2.1.283, interactive sessions start in auto mode, not Manual
  (settings-023).
- The built-in Explore subagent runs on the session's model, not Haiku
  (verif-066).
- A hook on Edit or Write does not stop edits made through the shell, and
  Read or Edit deny rules do not stop shell reads and writes (hooks-034,
  settings-020).
- An installed plugin costs context every turn, used or not (plugins-003).
