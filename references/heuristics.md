# Operational Heuristics (H1-H12)

Quick-access shortcuts. Each rule fired by the auditor traces back to one of these heuristics plus a verbatim Anthropic citation.

## H1 — Cite or Silence
Without a locatable Anthropic source, it is not an Anthropic rule. Drop it or downgrade to `EXTERNAL_ENRICHMENT` (non-Anthropic origin, reduced weight). Never silently invent.

## H2 — Surgical over Sweeping
Always the smallest diff that resolves the finding. Wholesale rewrites mask regressions. If a diff modifies > 40% of the artifact content, flag and require operator confirmation.

## H3 — Voice Drift Trumps Score
Raising the score by diluting authorial voice is a regression in disguise. Abort if `voice_drift_score > 10%`. Tighten to `5%` under `--push-ceiling`.

## H4 — Determinism First
What regex / line-count / frontmatter-parse can decide, decide deterministically. `llm-judge` only for purely qualitative dimensions (clarity-of-intent, voice consistency, semantic adequation). LLM calls are the most expensive instrument — reach for them last.

## H5 — Model-First Lens
The same Anthropic rule may have different recommended remediation by model. Always filter by `target_model` modulation profile before proposing a diff. A "raise effort" recommendation is meaningless on Haiku 4.5 (no effort param).

## H6 — Three-Strike Anti-Loop
After 3 multi-pass rounds without a +5pt gain, stop. Escalate diagnosis to operator with what was tried.

## H7 — Preserve-Then-Optimize
First inventory what is good (PRESERVE log). Then correct. Skipping the preserve pass destroys invisible wins.

## H8 — Pareto Cognitivo (STRATIFIED for >800 lines)
On large artifacts, 80% of impact comes from 20% of blocks. Map → triage by risk × impact → deep-audit top-K (default K=5). Never produce more than 15 simultaneous 🔴/🟡 findings (Miller × 3 cap).

## H9 — Miller × 3 Cap
Hard limit: 15 active 🔴/🟡 findings per report. Beyond → split into thematic reports.

## H10 — Freshness Audit
If `dissected_at` of any rule is > 90 days old, emit a staleness warning in the report. Recommend re-dissecting the Anthropic source page and bumping `meta.dissection_date` in `references/rules-anthropic.yaml`.

## H11 — Artifact-Type-First Selection ⚡
**Before applying any rule**, classify the artifact and load only the rule subset for that type from `rubric-by-type.yaml`. Auditing CLAUDE.md with skill rules guarantees false positives. This is the single most common audit mistake.

## H12 — Verification-as-Component ⚡
For any prompt/skill that produces a concrete artifact, demand an embedded verification criterion (test, screenshot, expected output). If absent → finding 🔴 (rule `AR2-EVAL-001`, "the single highest-leverage thing you can do").

---

## Detection Method Priority

When implementing audits, prefer in order:

1. **regex** (cheap, deterministic) — line-level patterns, ALL-CAPS detection, path slash style, frontmatter keys
2. **code-check** (script, deterministic) — line counts, parse YAML/MD validity, char counts, schema validation
3. **heuristic** (script, threshold-based) — sentence count, paragraph density, vocabulary repetition
4. **llm-judge** (last resort, expensive) — clarity-of-intent, voice drift, semantic adequation, "is this third person"

**Cost discipline (L8):** if a finding can be raised by `regex` but you used `llm-judge`, you wasted cost. Re-implement.

---

## Triage Cheatsheet

| If finding has... | Then triage as... |
|---|---|
| `severity: hard` OR `critical` OR `never` | 🔴 MUST-FIX |
| `severity: soft` OR `high` AND model-target affected | 🔴 MUST-FIX |
| `severity: soft` OR `high` AND no model impact | 🟡 SHOULD-FIX |
| `severity: medium` | 🟡 SHOULD-FIX |
| `severity: low` OR `warning` OR `consider` | 🟢 MAY-FIX |
| Pattern is consistent in author's other artifacts | ⚪ PRESERVE (note in report) |
| Rule fires but lives in `false_positive_rules` for this type | DO NOT EMIT (suppress) |
