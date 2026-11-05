# Doctrine Detail — model modulation, emphasis conflict, self-audit exception, scope

> Moved from SKILL.md body (poda 2026-07-02) to keep the body under budget. The body
> keeps the compact tables/pointers; load this file for the full prose reasoning.

## Target-model modulation (full detail)

Each model has a profile cell in `references/modulation-matrix.yaml`. Critical
anti-patterns flagged automatically (sources: per-model prompting pages
`prompting-claude-opus-4-8`, `prompting-claude-sonnet-5`,
`prompting-claude-fable-5` + `models/migration-guide`, fetched 2026-07-11):

- **Fable 5** (`claude-fable-5`) — rejects non-default `temperature` /
  `top_p` / `top_k` (HTTP 400), rejects prefill (400), rejects
  `thinking:{type:disabled}` AND `budget_tokens` (400) — thinking is always
  on; omit the field. Raw chain of thought never returned (`display:
  summarized|omitted`). Safety classifiers can decline with
  `stop_reason:"refusal"` — audit for fallback handling (e.g. to Opus 4.8).
  Start effort at `high`, not `xhigh` — lower effort often exceeds prior
  models' xhigh. Over-prescriptive skills/prompts degrade output. Dispatches
  subagents readily: guidance should govern, not encourage.
- **Opus 4.8** (`claude-opus-4-8`) — rejects `temperature` / `top_p` /
  `top_k` (400), rejects manual `thinking:{enabled,budget_tokens}` (400),
  rejects prefill (400). Thinking OFF unless `thinking:{type:adaptive}` is
  set explicitly. Interprets prompts literally — state scope explicitly.
  Effort levels strict; start `xhigh` for coding/agentic, ≥64k max_tokens at
  xhigh/max. Favors reasoning over tool calls — raise effort or prompt
  explicitly when more tool use is wanted. Spawns fewer subagents by
  default. Persistent design house style (cream/serif/terracotta) — specify
  concrete alternatives, generic negation bounces. Code-review prompts with
  "only high-severity"/"be conservative" depress recall.
- **Sonnet 5** (`claude-sonnet-5`) — rejects non-default sampling params
  (400 — new for Sonnet-class), rejects `budget_tokens` (400), rejects
  prefill (400). Adaptive thinking ON by default (inversion vs Sonnet 4.6) —
  `thinking:{type:disabled}` to turn off. New tokenizer: ~30% more tokens
  than 4.6; 4.6-tuned `max_tokens` may truncate. Effort default `high`;
  `xhigh` only for hardest coding/agentic (Sonnet 5 @ medium ≈ 4.6 @ high).
  More agentic than 4.6 by default, EXCEPT with thinking disabled, where it
  under-reaches for tools — add an explicit nudge. Literal instruction
  following, task-calibrated verbosity, and the code-review recall caveat
  all apply as on Opus 4.8.
- **Opus 4.7** *(legacy)* — same API rejections as Opus 4.8 (sampling
  params, budget_tokens, prefill → 400). Interprets prompts literally.
  ALL-CAPS imperatives over-suppress output. Guidance published for 4.7 was
  re-issued under Opus 4.8's name; profiles kept separately in the matrix.
- **Opus 4.6 / Sonnet 4.6** *(legacy)* — reject prefill (400). Adaptive
  thinking recommended (opt-in); `budget_tokens` deprecated but functional.
  Sampling params still accepted.
- **Haiku 4.5** — adaptive thinking unsupported, `effort` parameter
  unsupported, 200k-token context. Needs maximum explicitness; few-shot is
  more critical (5+ examples).

When a target model lacks a profile (e.g., a new release), inherit from the
closest sibling and stamp the report with `confidence: low`. Fallback rules
live in `references/modulation-matrix.yaml`.

## Emphasis conflict (D9, type-aware) — full detail

Two Anthropic sources disagree about ALL-CAPS / `IMPORTANT` / `YOU MUST`:

- `code.claude.com/docs/en/best-practices` endorses emphasis to tune adherence.
- `github.com/anthropics/skills/skill-creator` flags ALL-CAPS as yellow,
  preferring an explanation of the underlying reason.

Resolution applies by artifact type (table lives in SKILL.md body). When
AR-CC-S09 fires on a `claude_md`, suppress it as a false positive (anti-pattern
AP-10).

## Scope discipline (positive framing) — full detail

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

## Self-audit: Open Questions — full justification

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
