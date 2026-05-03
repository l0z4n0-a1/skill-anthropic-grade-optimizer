---
name: anthropic-grade-optimizer
description: Audits and optimizes Claude-directing artifacts (CLAUDE.md, SKILL.md, subagent, hook, MCP config, system or user prompt, workflow, api_config) against 189 cited Anthropic rules across 11 dimensions, calibrated per model (Opus 4.7, Sonnet 4.6, Opus 4.6, Haiku 4.5). Every finding ships with verbatim quote and source URL; authorial voice is preserved.
when_to_use: Operator asks to audit, optimize, review, lint, score, refactor, or "make Anthropic-grade" any prompt, CLAUDE.md, SKILL.md, subagent, hook, MCP config, api_config, or workflow. Also triggers on model migration ("good for Opus 4.7?", "optimize for Haiku"), compliance review, or fixing adherence/verbosity/hallucination drift in a Claude artifact.
---

# Anthropic-Grade Optimizer

Audits any Claude-directing artifact against the official Anthropic doctrine,
calibrates findings by target model, and proposes surgical optimizations that
preserve authorial voice. Every finding cites a verbatim source URL; the skill
ships with cited rules only.

## Contents

- Hierarchy of authority
- Honest scope
- Quick start (and worked examples)
- The Three Laws
- Artifact types (9)
- Target-model modulation
- The 11 dimensions
- Severity → triage
- Emphasis conflict (D9, type-aware)
- Detection methods
- Operating modes
- Adaptive modes (auto-trigger)
- Output format (concise default)
- Workflow (10 steps)
- Scope discipline (positive framing)
- Edge cases
- Self-audit: Open Questions
- References (10 files)
- Assets (canonical snippets)
- Scripts (6 entry points)
- Validation (eval suite + strange-loop)

## Hierarchy of authority

Anthropic doctrine is the sole source of scoring rules. Optional interpretive
lenses inform *how* to reason about findings (what to preserve, when to defer,
how to phrase recommendations) — they stay outside the rubric. On collision,
Anthropic always wins.

## Honest scope

189 unique cited rules across 11 dimensions, each with a verbatim quote and
source URL. Read `references/rules-anthropic.yaml` § `meta.total_unique_rules`
for the canonical count — every other counter in the skill must read from
there to prevent drift. Rules with deterministic detection (regex,
code-check) are audited automatically by `scripts/pass1_mechanical.py`. Rules
with qualitative criteria (llm-judge, heuristic) are audited by following
`references/pass2-protocol.md`. Coverage gaps and known limitations live in
`references/gaps.md` and must appear in the `coverage_caveat` block of every
report.

Pass-1 deterministic coverage in v1.2: ~52 rules (~28% of 189). Pass-2
covers the remaining ~137 qualitative rules. Hybrid detection is supported via
the `requires_pass2_grade` flag on findings.

## Quick start

**Canonical entry point (default):**

```
python scripts/run.py <artifact_path> --target opus-4-7 --mode audit
```

The orchestrator chains classify → pass 1 → score → emit, and surfaces Pass 2
prompts for the LLM. This is the single right answer for ~95% of audits.

**Manual flow** is for one specific case: an operator forcing fine-grained
control over a single phase (re-running pass 1 only, scoring an external
findings file, debugging the classifier). Do not use it as a parallel path —
the orchestrator is the contract.

1. **Ingest** — receive the artifact path or content, target model
   (default `opus-4-7`), mode (default `audit`).
2. **Classify** — Run `scripts/classify_artifact.py` to detect artifact type
   and load the rule subset from `references/rubric-by-type.yaml`.
3. **Audit** — Pass 1 mechanical via `scripts/pass1_mechanical.py`. Pass 2
   qualitative reasoning following `references/pass2-protocol.md` against
   `references/rules-anthropic.yaml`.
4. **Diagnose** — Classify each finding as 🔴 must-fix, 🟡 should-fix,
   🟢 may-fix, ❓ open-question, or ⚪ preserve (authorial voice).
5. **Optimize** *(when mode = optimize or full)* — Produce surgical diffs
   per `references/pass2-protocol.md` § Diff Generation. Each diff cites
   `source_url` + `verbatim_quote`. When a rule has a canonical snippet,
   emit a verbatim patch from `assets/snippets/` rather than paraphrasing.
6. **Validate** *(when mode = full)* — Re-score post-diff; abort when a
   hard rule is introduced or voice drift exceeds 10%.
7. **Emit** — Concise report (summary + scorecard + diff). Verbose mode
   adds reasoning trail, preservation log, and open questions.

### Worked example 1 — auditing a SKILL.md for Opus 4.7

<example>
Operator request: "audit this skill for Opus 4.7"
Artifact: `~/.claude/skills/pdf-tools/SKILL.md` (240 lines)

Step 1 — Classify: type=`skill`, has_frontmatter=true, body_lines=235.
Step 2 — Load rubric: 24 D-SKILL rules + 17 D-CLAR + 10 D-STRUCT + 8 D-EXAMPLE +
         5 D-EVAL + safety. Suppress AR-CC-S09 doctrine-conflict?  No (skill body).
Step 3 — Pass 1 fires: AR-CC-S20 (lib mentioned without `pip install`), AR-CC-S22
         (3 script refs unframed), AR-CLAR-006 (7 negatives, 1 positive alt).
Step 4 — Triage: 1 🔴 (AR-CC-S20), 2 🟢 (S22, CLAR-006).
Step 5 — Optimize emits snippet patches: none (no rule with canonical snippet
         fires). Inline diff for AR-CC-S20 adds "Install required package: pip install pypdf".
Step 6 — Validate: post-diff score 92 (was 78). Voice drift 4% — under 10% gate.
Step 7 — Emit concise report.
</example>

### Worked example 2 — strange-loop self-audit

<example>
Operator request: "run the skill on its own SKILL.md"
Artifact: `anthropic-grade-optimizer/SKILL.md`

Step 3 — Pass 1 fires: AR-CC-S14 (name contains "anthropic" reserved word) and
         possibly AR-CC-S21 (TOC) and AR-CC-S22 (script framing).
Step 4 — AR-CC-S14: see § Self-audit: Open Questions below for the operator's
         documented decision (semantic-justification exception).
Step 5 — No-op for the AR-CC-S14 finding (declared exception).
Step 7 — Concise report flags the open question and links to the §.
</example>

### Worked example 3 — auditing an api_config snippet

<example>
Operator request: "is this Python snippet safe for Opus 4.7?"
Artifact: a `client.messages.create(...)` call with `temperature=0.7`,
          `effort='low'`, last message role=assistant.
Type: `api_config`. Target: `claude-opus-4-7`.

Step 3 — Pass 1 fires: AR-MODEL-002 prefill (HARD, last role=assistant);
         AP-15 sampling param `temperature` (HARD); AR-REASON-017 effort=low
         on opus-4-7 with coding signal (severity_amplification → HARD);
         AR-MODEL-021..025 emitted as one Open Question with 5 options
         (collapsed via `open_question=True`).
Step 4 — Triage: 3 🔴 (002, AP-15, REASON-017), 1 ❓ (021..025).
Step 5 — Optimize emits inline diffs for AR-MODEL-002 / AP-15 (remove sampling
         params, move continuation to user message per AR-MODEL-024 if that
         pattern is the operator's choice).
</example>

## The Three Laws

These three laws encode the discipline that separates Anthropic-grade from
"looks rigorous":

1. **Cite or stay silent.** Every 🔴 / 🟡 finding carries a `source_url`.
   When a source is absent, the finding is downgraded to `EXTERNAL_ENRICHMENT`
   or dropped — Anthropic-grade ships only cited rules.
2. **Artifact type comes first.** Apply the rule subset for the detected
   type. Firing a SKILL.md rule against a CLAUDE.md is a false positive — see
   `references/rubric-by-type.yaml` § `false_positive_rules`.
3. **Voice drift trumps score.** Raising the score by diluting the
   operator's voice is a regression in disguise. Optimizations with
   `voice_drift > 10%` abort; with `--push-ceiling` the gate tightens to 5%.

## Artifact types (9)

Detection happens on filename plus content; each type loads a tailored rule
subset from `references/rubric-by-type.yaml`:

| Type | Path signal | Primary dimensions |
|---|---|---|
| `claude_md` | `CLAUDE.md`, `CLAUDE.local.md` | D-CC (memory), D-CLAR, D-STRUCT |
| `skill` | `SKILL.md` in `skills/<name>/` | D-CC (skill), D-CLAR, D-STRUCT |
| `slash_command` | `.claude/commands/<name>.md` (legacy) | D-CC (skill subset) |
| `subagent` | `.claude/agents/<name>.md` | D-CC (subagent), D-AGENT, D-CLAR |
| `hook_config` | `settings.json` `hooks` key | D-CC (hooks) |
| `mcp_config` | `.mcp.json`, `.claude.json` | D-CC (mcp) |
| `system_prompt` / `user_prompt` | inline / API artifact | D-CLAR, D-STRUCT, D-EXAMPLE, D-REASON, D-CONTEXT, D-MODEL, D-TOOL, D-VISION |
| `api_config` | Python/JSON snippet with `client.messages.create` or `model="claude-..."` | D-MODEL, D-REASON, D-CONTEXT (cache), D-TOOL, D-VISION |
| `workflow` | YAML pipeline | D-AGENT, D-EVAL |

## Target-model modulation

Each model has a profile cell in `references/modulation-matrix.yaml`. Critical
anti-patterns flagged automatically:

- **Opus 4.7** — rejects `temperature` / `top_p` / `top_k` (HTTP 400),
  rejects manual `thinking:{enabled,budget_tokens}` (400), rejects prefill
  on the last assistant turn (400). Interprets prompts literally — state
  scope explicitly. ALL-CAPS imperatives over-suppress output. Effort levels
  are strict; pair `xhigh` with coding/agentic. Tool use decreases by
  default; raise effort or prompt explicitly when more tool use is wanted.
- **Opus 4.6 / Sonnet 4.6** — rejects prefill (400). Adaptive thinking is
  recommended.
- **Haiku 4.5** — adaptive thinking unsupported, `effort` parameter
  unsupported, 200k-token context. Needs maximum explicitness; few-shot is
  more critical (5+ examples).

When a target model lacks a profile (e.g., a new release), inherit from the
closest sibling and stamp the report with `confidence: low`. Fallback rules
live in `references/modulation-matrix.yaml`.

## The 11 dimensions

| Dim | Focus | Weight |
|---|---|---|
| D-CLAR | Clarity, directness, positive framing | 16% |
| D-STRUCT | XML tags, hierarchy, formatting | 11% |
| D-EXAMPLE | Few-shot 3-5 examples in `<example>` | 8% |
| D-REASON | CoT, adaptive thinking, self-check | 12% |
| D-CONTEXT | Doc placement, grounding, cache | 10% |
| D-MODEL | Model-specific calibration | 10% |
| D-AGENT | Stop conditions, ground truth, delegation | 8% |
| D-EVAL | Verification embedded in prompt | 7% |
| D-TOOL | Tool definitions, schemas, parallel | 6% |
| D-VISION | Image placement, coords, formats | 4% |
| D-CC | Claude Code ecosystem (memory/skill/agent/hook/MCP) | 8% |

## Severity → triage

| Severity | Score impact | Triage |
|---|---|---|
| `hard` / `critical` / `never` | -10 to -20 | 🔴 must-fix |
| `soft` / `high` | -5 to -8 | 🟡 should-fix |
| `medium` | -3 to -5 | 🟡 should-fix |
| `low` / `warning` | -1 to -2 | 🟢 may-fix |
| (5+ migration options, group fix) | n/a | ❓ open-question |
| (authorial voice signal) | n/a | ⚪ preserve |

## Emphasis conflict (D9, type-aware)

Two Anthropic sources disagree about ALL-CAPS / `IMPORTANT` / `YOU MUST`:

- `code.claude.com/docs/en/best-practices` endorses emphasis to tune adherence.
- `github.com/anthropics/skills/skill-creator` flags ALL-CAPS as yellow,
  preferring an explanation of the underlying reason.

Resolution applies by artifact type:

| Artifact type | Emphasis verdict |
|---|---|
| `claude_md`, `system_prompt`, `user_prompt` | Endorsed (suppress yellow-flag finding) |
| `skill`, `subagent` body | Yellow flag (raise finding, explain WHY) |
| `tool_description` | Neutral (no doctrine) |

When AR-CC-S09 fires on a `claude_md`, suppress it as a false positive
(anti-pattern AP-10).

## Detection methods

Prefer determinism (cheapest instrument that solves):

- **regex** / **code-check** → `scripts/pass1_mechanical.py`
- **heuristic** (line counts, structural shape) → `scripts/pass1_mechanical.py`
- **hybrid** (regex emits candidate, LLM grades substance) → Pass 1 emits
  with `requires_pass2_grade=true`; Pass 2 finalizes
- **llm-judge** → reason directly with the artifact text loaded; cite the
  rule + verbatim quote

Reach for `llm-judge` only when no script can decide.

## Operating modes

- `audit` *(default)* — read-only report, no diffs proposed.
- `optimize` — generate diffs without validating.
- `full` — audit → optimize → validate → emit. Loops up to three passes
  when score < 85.
- `--push-ceiling` — applies may-fix (🟢) findings; tightens voice_drift to 5%.
- `--fast` — top-5 findings only; single pass.
- `--no-exceptions` — disables operator-declared exceptions (see § Self-audit).
  Reports the strict raw score instead of the active score. The orchestrator
  always shows both side by side when an exception is in effect, so this flag
  is for downstream tooling that needs the unadjusted number.

## Adaptive modes (auto-trigger)

| Trigger | Mode | Effect |
|---|---|---|
| Artifact > 800 lines | STRATIFIED-AUDIT | Map blocks → triage → deep-audit top-K (default K=5) |
| Initial score ≥ 85 + zero 🔴 | AFFIRMATION | Short report; surface 🟢 only with `--push-ceiling` |
| Artifact < 50 tokens + minimal markers | HIGH-UNCERTAINTY | Ask "intentional brevity or unfinished?" before expanding |
| Target model lacks profile | FALLBACK-MODEL | Inherit sibling, mark `INFERRED`, reduce D-MODEL weight 10% → 5% |

## Output format (concise default)

```
ANTHROPIC-GRADE OPTIMIZER REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Artifact: <path>
Type: <type> | Target: <model> | Mode: <mode> | Rules: v1.2 (189)

SCORE: <0-100>  (<grade>)
  D-CLAR: <n>%   D-STRUCT: <n>%   D-EXAMPLE: <n>%
  D-REASON: <n>% D-CONTEXT: <n>%  D-MODEL: <n>%
  D-AGENT: <n>%  D-EVAL: <n>%     D-TOOL: <n>%
  D-VISION: <n>% D-CC: <n>%

FINDINGS: <count_red> 🔴 / <count_yellow> 🟡 / <count_green> 🟢 / <count_q> ❓ / <count_preserve> ⚪

🔴 Must-fix
  [F-001] <rule_id> — <one-line statement>
    Location: <line range>
    Source: <source_url>
    Quote: "<verbatim>"

🟡 Should-fix
  ...

❓ Open questions (operator decides)
  [Q-001] <rule_id> — <options summary>

DIFF (mode ≠ audit):
  <unified diff with rule citations>
SNIPPET PATCHES (when applicable):
  <verbatim insertions from assets/snippets/ with source_url>

COVERAGE CAVEAT:
  Doctrine dissected on 2026-05-02. 189 cited rules. Gaps in references/gaps.md.
  <if model is INFERRED>: Target model profile inherited; confidence: low.
```

Verbose adds: per-finding reasoning trail, preservation log (what stayed and
why), and explicit open questions for authorial decisions.

## Workflow

1. Run `python scripts/classify_artifact.py <path>` → `{type, line_count, signals}`.
2. Read `references/rubric-by-type.yaml` for the type's rule_ids.
3. Run `python scripts/pass1_mechanical.py <path> --type <type> --target-model <model>`
   → deterministic findings (including hybrid candidates).
4. For each rule with `detection_method=llm-judge` in the type's subset,
   read the relevant section, reason about adherence, cite the rule's
   `verbatim_quote`, and append the finding to the bundle.
5. Apply D9 emphasis-conflict resolution by artifact type
   (see `references/rubric-by-type.yaml` § `false_positive_rules`).
6. Run `python scripts/score_calculator.py <findings.json>`
   → `{score, per_dimension, voice_drift_estimate}`.
7. Triage findings (🔴/🟡/🟢/❓/⚪).
8. When mode ≠ `audit`, run `python scripts/optimize.py <path> --findings <json> --type <type>`
   to produce surgical diffs and snippet patches (each cited).
9. When mode = `full`, simulate post-diff, re-score, validate gate.
10. Emit report (concise default; verbose with `--verbose`).

## Scope discipline (positive framing)

This skill audits prompts and Claude-directing artifacts. Its responsibilities:

- **Audits**: cited findings only, with `verbatim_quote` + `source_url`.
- **Proposes diffs**: surgical, one rule per diff, voice-preserving.
- **Stays in source language**: preserves the artifact's authorial voice.
- **Defers to operator**: the operator stays in the editor's seat — diffs
  apply only with `--apply` to an `<path>.optimized.<ext>` sibling, never
  overwriting the original.

Out-of-scope (sibling tools handle these):

- Evaluating Claude's *responses* — that work belongs to eval pipelines.
- Auditing application code that *consumes* the Claude API beyond the
  prompts and artifacts themselves.
- Inventing rules without a source URL — every finding ships cited.

## Edge cases

When a rule could fire but no verbatim source quote can be found, hold the
finding back. Add it to the report's `coverage_caveat` block as a candidate
for the next dissection round. Anthropic-grade means cited or silent.

When two rules conflict and no documented resolution exists (see
`references/gaps.md` for the 10 known conflicts), surface both findings and
elevate the decision to the **open questions** block — the operator decides.

## Self-audit: Open Questions

The skill audits itself on every release via the canonical entry point:

```
python scripts/run.py SKILL.md --target opus-4-7 --mode audit
```

Declared exceptions (operator-justified, registered in `scripts/run.py § DECLARED_EXCEPTIONS`):

- **AR-CC-S14 — reserved word "anthropic" in name.** The doctrine quote
  *"Cannot contain reserved words: 'anthropic', 'claude'."* applies to skill
  names. The operator decision is to keep the name
  `anthropic-grade-optimizer` because it is the most precise descriptor of
  the skill's purpose. A rename to `doctrine-grade-optimizer` would lose the
  explicit doctrinal anchor and degrade trigger reliability for operators
  searching by domain. The Pass-1 detector continues to flag it on every
  run; the orchestrator splits the report into `active score` (exception
  applied) and `raw score` (`--no-exceptions`) so consumers retain full
  information. D-CC dimension shows the residual penalty
  transparently — voice fidelity over hidden adjustment.

The full self-audit run, including findings, both scores, and dimension
breakdown, is committed at `evals/SELF-AUDIT.md` and re-runs on every release.

## References (10 files in `references/`)

- `rules-anthropic.yaml` — 189 rules with `source_url` + `verbatim_quote` +
  `detection_method` (v1.2). The canonical SSOT for rule count and content.
- `rules-master.yaml` — index by dimension (points into rules-anthropic.yaml).
- `modulation-matrix.yaml` — 4 models × ~10 cells, each
  `{value, source_url, confidence}`.
- `rubric-by-type.yaml` — rule subsets per artifact type, with
  false-positive suppression matrix and 3 documented doctrinal conflicts.
- `quotes-canonical.md` — verbatim citations for report output.
- `heuristics.md` — H1-H12 operational shortcuts.
- `anti-patterns.md` — AP-1 to AP-15 with detection method.
- `gaps.md` — known doctrinal gaps (declare in every report).
- `pass2-protocol.md` — qualitative auditing workflow (llm-judge rules).

## Assets (canonical snippets)

- `assets/snippets/` — 18 canonical snippets (16 rule-bound + 2 advisory).
  Every snippet is byte-by-byte verbatim from the live Anthropic doc, with
  a header table declaring `triggers_rule`, `applies_to`, `model_specific`,
  `source_url`, `insertion_pattern`, and `voice_drift`. Snippets cover
  high-leverage rules: AR-MODEL-018 (code-review coverage), AR-MODEL-011
  (investigate before answering), AR-MODEL-007/AR-AGENT-009 (parallel
  tool calls), AR-CLAR-011 (action vs research posture, two snippets),
  and 12 more.
- `assets/snippets/index.yaml` — `rule_id → snippet` map consumed by
  `scripts/optimize.py`. Type-aware suppression prevents AP-9 false patches
  (e.g., subagent files never receive subagent-orchestration snippets).

## Scripts (6 entry points in `scripts/`)

- `run.py` — orchestrator; runs classify → pass 1 → score → emit. Single
  entry point for most workflows.
- `classify_artifact.py <path>` — returns
  `{type, line_count, language, has_frontmatter, signals}`.
- `pass1_mechanical.py <path> --type <type> --target-model <model>` —
  emits findings array (regex + code-check + hybrid candidates).
- `score_calculator.py <findings.json>` — emits
  `{score, per_dimension, voice_drift_estimate}`.
- `optimize.py <path> --findings <json> --type <type> [--apply]` — emits
  diffs and snippet patches; with `--apply` writes to
  `<path>.optimized.<ext>` (preserving the original).
- `run_eval_suite.py` — replays `evals/fixtures/` ground-truth suite.

All scripts use forward slashes and read paths via the `CLAUDE_SKILL_DIR`
env var, defaulting to the parent of the script directory (per AR-CC-S06).
On Windows, scripts force UTF-8 stdout to render the triage glyphs
(🔴/🟡/🟢/❓/⚪) without `cp1252` crashes.

## Validation (eval suite + strange-loop)

The skill validates itself via `evals/`. The fixture set covers good /
bad / adversarial-minimal cases for every artifact type, plus cross-type
fixtures that exercise the false-positive suppression matrix. Ground-truth
scores live in `evals/ground-truth.yaml`; `scripts/run_eval_suite.py`
replays them. The strange-loop self-audit
(`evals/SELF-AUDIT.md`) re-runs the skill against its own SKILL.md on every
release and commits the result for transparency.
