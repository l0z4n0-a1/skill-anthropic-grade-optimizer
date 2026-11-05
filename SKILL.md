---
name: anthropic-grade-optimizer
description: "Audits and optimizes Claude-directing artifacts (CLAUDE.md, SKILL.md, subagent, hook, MCP config, prompt, workflow) against 189 cited Anthropic rules across 11 dimensions, calibrated per target model. Findings ship with verbatim quote + source URL; authorial voice preserved. Escopo: COMPLIANCE vs. regras Anthropic citadas (não estrutura, não custo)."
when_to_use: "Audit, optimize, lint, score, refactor, or \"make Anthropic-grade\" any Claude artifact; model migration (\"good for Haiku?\"); fixing adherence/verbosity/hallucination drift."
---

# Anthropic-Grade Optimizer

Audits any Claude-directing artifact against the official Anthropic doctrine,
calibrates findings by target model, and proposes surgical optimizations that
preserve authorial voice. Every finding cites a verbatim source URL; the skill
ships with cited rules only.

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
python scripts/run.py <artifact_path> --target opus-4-8 --mode audit
```

The orchestrator chains classify → pass 1 → score → emit, and surfaces Pass 2
prompts for the LLM (full step-by-step in § Workflow below). This is the single
right answer for ~95% of audits. Manual flow (running one phase in isolation —
re-running pass 1 only, scoring an external findings file, debugging the
classifier) exists for that one specific case; never use it as a parallel path.

### Worked example — auditing a SKILL.md for Opus 4.7 (golden)

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

❌ Negative twin, and 2 more worked examples (strange-loop self-audit, api_config
snippet): `references/worked-examples.md`.

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

Each model has a profile cell in `references/modulation-matrix.yaml`. Fable 5,
Opus 4.8, and Sonnet 5 all reject non-default sampling params, prefill, and
manual `budget_tokens` thinking (HTTP 400) and interpret prompts literally —
state scope explicitly. Thinking defaults diverge: Fable 5 always-on (`disabled`
→ 400), Sonnet 5 on by default, Opus 4.8 off unless `{type: adaptive}` is set.
Sonnet 5 uses a new tokenizer (~30% more tokens vs 4.6). Fable 5 inverts two
4.8 heuristics: start effort at `high` (not `xhigh`) and govern — don't
encourage — subagent spawning. Opus 4.7/4.6 and Sonnet 4.6 are legacy (prefill
also 400); Haiku 4.5 has no adaptive thinking/effort param and needs maximum
explicitness (5+ few-shot). Missing profile → inherit closest sibling, mark
`confidence: low`. Full per-model anti-pattern detail:
`references/doctrine-detail.md` § Target-model modulation.

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

Two Anthropic sources disagree on ALL-CAPS/`IMPORTANT`/`YOU MUST` (endorsed for
adherence-tuning vs flagged yellow for skill bodies). Resolution by artifact type:

| Artifact type | Emphasis verdict |
|---|---|
| `claude_md`, `system_prompt`, `user_prompt` | Endorsed (suppress yellow-flag finding) |
| `skill`, `subagent` body | Yellow flag (raise finding, explain WHY) |
| `tool_description` | Neutral (no doctrine) |

AR-CC-S09 on a `claude_md` → suppress as false positive (AP-10). Full doctrine
quotes/sources: `references/doctrine-detail.md` § Emphasis conflict.

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

## Scope discipline

Audits + proposes voice-preserving surgical diffs (never overwrites the
original — writes to `<path>.optimized.<ext>` only with `--apply`). Out of
scope: evaluating Claude's responses (eval pipelines' job), auditing
application code beyond the prompt/artifact itself, inventing uncited rules.
Full framing: `references/doctrine-detail.md` § Scope discipline.

## Edge cases

When a rule could fire but no verbatim source quote can be found, hold the
finding back. Add it to the report's `coverage_caveat` block as a candidate
for the next dissection round. Anthropic-grade means cited or silent.

When two rules conflict and no documented resolution exists (see
`references/gaps.md` for the 10 known conflicts), surface both findings and
elevate the decision to the **open questions** block — the operator decides.

## Self-audit: Open Questions

The skill audits itself every release: `python scripts/run.py SKILL.md --target
opus-4-8 --mode audit`. One declared exception is registered in
`scripts/run.py § DECLARED_EXCEPTIONS`: **AR-CC-S14** (reserved word
"anthropic" in the skill name) — kept deliberately, `--no-exceptions` shows the
raw score. Full justification + self-audit provenance:
`references/doctrine-detail.md` § Self-audit.

## References, assets, scripts, validation

Detailed map (file-by-file, script args, snippet coverage, CI/tests note):
`references/scripts-and-assets-map.md`. Quick index:

- `references/` (12 files) — `rules-anthropic.yaml` (189 rules, canonical SSOT),
  `rules-master.yaml`, `modulation-matrix.yaml`, `rubric-by-type.yaml`,
  `quotes-canonical.md`, `heuristics.md`, `anti-patterns.md`, `gaps.md`,
  `pass2-protocol.md`, `worked-examples.md`, `scripts-and-assets-map.md`,
  `doctrine-detail.md`.
- `assets/snippets/` — 18 canonical, byte-verbatim Anthropic snippets +
  `index.yaml` (`rule_id → snippet`).
- `scripts/` — 6 entry points: `run.py` (orchestrator), `classify_artifact.py`,
  `pass1_mechanical.py`, `score_calculator.py`, `optimize.py`, `run_eval_suite.py`.
- `evals/` + `tests/` — validation suite and self-audit (`evals/SELF-AUDIT.md`).
  Kept in place, not relocated — see map file for why.

---

**Exceção declarada (poda 2026-07-02):** corpo em ~291L / ~14KB — acima do alvo
≤250L/8KB. 5 seções foram extraídas para references (worked-examples,
doctrine-detail ×4 subsections, scripts-and-assets-map) e o TOC + a lista manual
de 7 passos (redundante com Workflow) foram cortados. O que resta é 100%
estrutura de execução exigida por SKILL-FORM Intelligence rules: tabelas de tipo/
dimensão/severidade (shape que o modelo preenche), os 10 passos do Workflow, e o
1 golden example — cortar mais viraria "trimmed by deleting steps", proibido.
L3 não invocado — decisão de forma.
