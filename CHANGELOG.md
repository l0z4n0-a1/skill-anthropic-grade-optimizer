# Changelog

All notable changes to the anthropic-grade-optimizer skill follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
