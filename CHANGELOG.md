# Changelog

All notable changes to the anthropic-grade-optimizer skill follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-11-14 - From rule engine to setup instrument

Version 2 is a different tool. Claude Code now ships `/doctor prompt-audit` for
line-level review of instruction text, which is what version 1 did, so version 2
moves to what the built-in checks do not ask: how the pieces of a setup work
together, and whether each is good at its job.

### Added
- `scripts/measure.py`: lists every piece of a setup, when it loads, its estimated
  context cost, and 30 days of usage by model, tool, skill and agent from local
  session history. `--compare` shows what changed between two runs.
- `kb/`: 822 claims from 77 Anthropic sources, each with a verbatim quote, source
  and read date, covering Claude Opus 5.5, Sonnet 5.5, Haiku 5.5 and Fable 5.2.
- `scripts/kb_gate.py`: rejects any claim whose quote is not in its source
  snapshot; after a fetch, this is also how stale claims are found.
- `scripts/kb_fetch.py` and `scripts/kb.py`: fetch sources by content hash, and
  select claims by topic and model for a review.
- `references/setup-review.md`, `piece-review.md`, `model-fit.md`,
  `maintaining.md`, and `kb/EXTRACTION.md`.
- Tests for measurement, the gate's failure cases and knowledge-base structure.

### Changed
- `SKILL.md` rewritten around three jobs: review a whole setup, review one piece,
  fit a setup to a model.
- Model-specific knowledge lives only in claims. A new model is a knowledge-base
  update, not an edit to the skill.

### Removed
- The 189-rule engine, its regex detectors, the 0-100 score, the voice-drift gate,
  snippets and fixtures. All remain at the `v1.0.0` tag. The score is not
  replaced: findings are ordered by effect and backed by measured figures.

## [1.0.1] — 2026-07-11 — Model Currency: Opus 4.8 / Sonnet 5 / Fable 5

### Changed
- **All 39 `model_specific` rules re-derived** against the restructured Anthropic docs. Model-specific guidance moved to dedicated pages (`prompting-claude-opus-4-8`, `prompting-claude-sonnet-5`, `prompting-claude-fable-5`); every affected quote, anchor, and model scope updated. Rule count unchanged (189); flags cleared to `verified-2026-07-11`.
- **`modulation-matrix.yaml` v1.2:** fable-5 / opus-4-8 / sonnet-5 profiles with behavioral cells sourced directly from the dedicated pages (inherited cells reduced to ambiguity_tolerance / optimal_density / few_shot_count). Fable 5 inversions encoded (effort start `high`; subagents govern-don't-encourage; over-prescription degrades).
- **`scripts/run.py`:** `--target` choices extended to fable-5 / opus-4-8 / sonnet-5; default is now `opus-4-8`.
- **`scripts/pass1_mechanical.py`:** api_config gates rebuilt — `is_strict_sampling` (opus-4-8/4-7, sonnet-5, fable-5), `is_strict_effort` (opus-4-8/4-7, sonnet-5 — NOT fable-5), prefill gate extended to 4.6+ incl. new family; finding strings/URLs updated to the 4.8-era sources.
- **`references/pass2-protocol.md`:** compound `model_specific` matching semantics defined (`;` scope commentary, `NOT`/`REVERSED` exclusions); Step-4 severity calibration extended to opus-4-8 / sonnet-5 / fable-5 (with Sonnet 5 effort exception and Fable 5 drops/reversals); AR-CLAR-009 notch-up removed for 4.7 (rule re-scoped to 4.5/4.6).
- **Snippets:** model-self-knowledge, frontend-aesthetics, steer-thinking, code-review-coverage, concise-output, subagent-spawning-4-7 — URLs, scopes, and doctrine quotes updated; Fable 5 insertion guards added where guidance reverses.
- **SKILL.md § Target-model modulation + `references/doctrine-detail.md`:** rewritten for the current family.
- **`references/quotes-canonical.md` / `references/gaps.md`:** quotes and gap notes synced to 2026-07-11 sources.

### Validation
- 212/212 unit tests · 15/15 eval fixtures · calibration ≥85% gate green · `check_model_currency.py` 4/4 · self-audit `--target opus-4-8`: 85/100 GATE=PASS (0 must-fix).

## [1.0.0] — 2026-05-02 — Signature Release

First public release. End-to-end audit pipeline with Pass-1 + Pass-2 + calibration + CI guards.

### Added
- **Pass-2 executor (`scripts/pass2_executor.py`):** real qualitative audit via the Claude API with prompt caching. Reads `llm-judge` rules from the SSOT, sends artifact + applicable rules to `claude-opus-4-7`, returns structured findings identical to Pass-1's schema. Graceful degradation without `ANTHROPIC_API_KEY` or the `anthropic` SDK.
- **Orchestrator `--pass2` flag:** chains Pass-2 into the canonical entry point. Reports include token usage and cache-read counts when the API call fires.
- **Model currency guard (`scripts/check_model_currency.py`):** versioned `KNOWN_CURRENT_MODELS` set. Fails CI when `modulation-matrix.yaml` lacks a profile for any known-current Anthropic model.
- **Per-rule unit tests (`tests/test_rule_schema.py`, `tests/test_pass1_detectors.py`, `tests/test_orchestrator.py`):** 212 pytest cases covering rule-schema integrity (one test per rule_id), pass-1 detector output shape, and orchestrator contract (bundle keys, exception handling, alias compatibility).
- **Calibration telemetry (`tests/calibration.py`):** computes per-class precision/recall/F1, confusion matrix, and per-fixture finding-count drift. Emits `evals/results/CALIBRATION_REPORT.md` and exits non-zero when overall accuracy drops below 85%.
- **Conflict-resolution tie-breakers:** `references/gaps.md § G3` documents 5 rule-conflict resolutions with rationale (was: open declared gap).
- **Signature artifacts:** `LICENSE` (MIT), `VERSION`, `CHANGELOG.md`, `.github/workflows/ci.yml`.
- **`--no-exceptions` flag:** disables operator-declared exceptions for the strict view.
- **Declared-exception registry:** `scripts/run.py § DECLARED_EXCEPTIONS` is the typed source of truth for operator-justified hard-rule exemptions.

### Changed
- **SSOT contract enforced:** `scripts/run.py` reads `meta.total_unique_rules` dynamically from `references/rules-anthropic.yaml`. Removed every hardcoded count across the codebase.
- **Frontmatter compressed** from 615 → 391 chars in `description`, preserving every trigger keyword while improving Opus 4.7 trigger precision.
- **Quick-start posture disambiguated:** orchestrator marked canonical default; manual flow scoped to forced-control case (closes literal-interpretation risk on Opus 4.7).
- **Self-audit doc rewritten** (`evals/SELF-AUDIT.md`) to reflect orchestrator-driven flow with raw + active scores side by side.

### Fixed
- **Schema bug `AR-VISION-010`:** severity was `must` (invalid); corrected to `hard`. Caught by the new unit-test suite.
- **Eval suite back-compat:** orchestrator bundle now includes `score` as alias for `score_active`, restoring `run_eval_suite.py` to 15/15.
- **Subprocess UTF-8 decode crashes** on adversarial fixtures (Windows `cp1252` defaults). All test runners use `errors="replace"`.

### Documentation
- `evals/SELF-AUDIT.md` — strange-loop closure with score timeline (E4 → E5 → E6).
- `evals/results/CALIBRATION_REPORT.md` — auto-generated precision/recall report.
- `evals/results/EVAL_MATRIX.md` — auto-generated 15-fixture pass/fail matrix.

### Score (signature self-audit)
- **Active: 98 / 100 (A — Anthropic-grade)** with operator-declared exception
- **Strict: 83 / 100 (B — Production)** without exception
- **Eval suite: 15 / 15 fixtures pass**
- **Unit tests: 212 / 212 pass**
- **Calibration: 93.3% accuracy**
- **Model currency: 4 / 4 known-current models covered**
