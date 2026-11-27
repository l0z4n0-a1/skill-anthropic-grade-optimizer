# Changelog

All notable changes to grade-optimizer follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/architecture.md`: components, trust boundaries, the claim lifecycle,
  design decisions, extension points and a glossary.
- `docs/example-report.md`: an unedited review of the `planted` calibration
  setup, scored against the answer key.
- `docs/troubleshooting.md`: symptom, cause and fix for install, permissions,
  headless runs and script exit codes.
- Issue and pull request templates, a code of conduct, and Dependabot for
  GitHub Actions.

### Fixed
- The 2.1.0 entry now says 142 sources cited of 148 catalogued, matching the
  README and NOTICE.

## [2.1.0] - 2026-11-27 - Process review, a measured knowledge base, and an update command

Version 2.0 reviewed the pieces of a setup. This release adds the thing people
build on top of them, a process that hands work between sessions, and it
measures how far the knowledge base itself can be trusted.

### Added
- `references/process-review.md`: a fourth job, reviewing an orchestration
  process (runner, workflow, review loop). It starts from the process's own run
  records, has the reviewer write down what the design predicts before
  counting, separates a symptom from its rival causes, and keeps a defect apart
  from a cost the owner would not fix.
- `references/foundations.md`: twelve older principles from measurement,
  control and systems design, for what no claim covers. Each entry keeps what
  the original says apart from what this skill takes from it, and a finding
  that rests on one is labelled `principle: <name>`, never as Anthropic's
  guidance.
- `/grade-optimizer:update` (`commands/update.md`, `scripts/kb_update.py`):
  checks how far the documentation has moved since the claims were read, safe
  on an installed copy; in a working clone it carries the knowledge base
  forward on a branch. A source that was fetched and not yet re-reviewed is
  recorded in `kb/pending.json`, and `kb.py` prints a notice beside every claim
  that rests on it until `--reviewed` clears it. Exit codes distinguish
  "nothing changed" from "could not compare everything".
- Knowledge base: 1,569 claims citing 142 sources, of 148 catalogued
  (was 822 claims, 82 sources catalogued). New topics
  cover verification and review loops, orchestration, the Agent SDK and
  headless runs, mods and auto mode, platform context management, containment,
  and coordination patterns. 35 of the new sources are Anthropic engineering
  and research posts (tier 2).
- Tier 3 sources: a person from Anthropic speaking in someone else's venue. A
  tier 3 claim opens by naming the speaker and reports practice, not guidance.
- `kb/core.json`: a `process` question, fourteen claims.
- `evals/build_process_fixtures.py`: a planted process (ten defects) and a
  clean one, with seeded run records so the answer key's counts are exact.
- `scripts/kb_gate.py` warns when a claim states a number its source never
  prints, and validates the shape of every claim, source, lock and
  `pending.json`: id form, global uniqueness, exactly one locator per source.
  A missing snapshot exits 3, apart from a failed claim (1) and misuse (2).
- `docs/reference.md`: every script's options, exit codes and JSON keys, and
  every data file's fields and what validates them.
- `measure.py --no-external-reads`, for a setup you did not write; `--user-config`;
  `schema_version` and a `policy` block in its JSON; a plugin whose `SKILL.md`
  sits at its root is now in the inventory.
- `kb_update.py --max-seconds`; `schema_version` in its JSON; `no_previous`
  lists changed sources with no trustworthy previous copy to diff against.
- Plugin icon and README banner.
- `NOTICE.md` states the basis for each kind of excerpt; the `claude-api`
  excerpts come from Apache-2.0 files, whose license is now in `LICENSES/`.
- README: headless and Agent SDK examples, each run before release.

### Changed
- Every claim was re-read against its source by a reader from a different
  model family than the one that extracted it, and tightened where it said
  more than the source. Every source was downloaded again on 2026-11-27: 65
  had changed and 66 are new, so 131 lock entries carry that date, and the 17
  that were byte-identical keep 2026-11-14. The claims of the 65 changed
  sources were re-read against the diffs.
- The skill is named `grade-optimizer`, like the plugin (it was
  `anthropic-grade-optimizer`). Agent Skill names may not contain `anthropic`
  or `claude`, and the old name read as if the project spoke for Anthropic.
  The plugin command is now `/grade-optimizer:grade-optimizer`.
- `NOTICE.md`: the MIT license covers the project's own material; quoted
  excerpts belong to their authors and are listed by kind of source.
- `SKILL.md`: read a claim's quote with `kb.py cite` before a finding rests on
  it; a claim that names a speaker is cited as that person's account.
- `references/maintaining.md`: a fidelity rate is stated only from two readers
  of different model families on the same sample, as the share neither
  faulted.
- Both fixture builders refuse an argument that looks like an option instead
  of creating a directory with that name.
- `kb_fetch.py` records a changed source in `kb/pending.json` before advancing
  the lock, as `kb_update.py --apply` does, so a download can no longer clear
  the "not yet reviewed" signal. `--reviewed` runs the gate and refuses if it
  fails.
- The update scripts refuse a redirect to a host outside the sources and
  indexes, cap each response at 5 MB, and date provenance in UTC.
- `measure.py`: effective settings precedence for enabled plugins; timestamps
  parsed with their offset; usage attributed with the plugin namespace;
  `--compare` validates its baseline completely before writing anything,
  refuses `--out` on the same file and refuses a baseline taken with
  different read options (a baseline from 2.0 must be measured again);
  `--no-external-reads` also confines subagent sidecar and `--piece` reads;
  `--out` never holds content with a wide file mode;
  invalid input exits 2 with a message instead of a traceback; a Windows hook
  command is no longer split as a POSIX shell line; cache-rebuild causes are
  reported as inferred.
- `kb.py` exits 2 for an unknown topic, question or claim id, distinct from a
  valid empty selection (1).
- CI runs on Python 3.9 and 3.12.

### Measured
- Fidelity: on a random sample of 60 claims, one reader faulted 7 and the other
  passed all 60 while noting 4 close calls; no overlap, and all 11 objections
  held against the source. 49 of 60 (82%) drew no objection from either
  reader. The 11 were faults of scope or a dropped condition, none contrary to
  its source, and were corrected. This is the result on that sample before
  correction; it does not establish a rate for the other 1,509 claims, which
  is why the skill has the reviewer read the quote.
- The gate passes with 0 errors and 1 warning (`skills-046`, a figure compared
  across two pages). 59 tests pass.
- Process guide, five blind rounds: on the planted process the last three
  found 9, 8 and 9 of 10 defects with 0, 1 and 0 false findings (the last 9
  counts one defect named by its code path without the count the key asks
  for); on the clean one, no invented finding in the last three rounds run,
  with residues presented as defects counted separately in `evals/README.md`
  (2 in the fourth round). The round that scored 8
  followed a revision of the guide, and its false finding was traced to one
  sentence, since corrected. `evals/README.md` has the table and what each
  round changed.

### Known limits
- `kb_update.py` has no lock against two updates at once, and its hash of an
  HTML source ignores link targets.
- Six bundled sources (135 claims) are compared only when `--bundled-dir` is
  given.
- The process guide has been run on one real process outside its fixtures,
  and the fixtures were built by the same hands as the guide. The clean
  fixture has one open true finding, listed in the answer key.

## [2.0.0] - 2026-11-14 - From rule engine to setup instrument

Version 2 is a different tool. Claude Code now ships `/doctor prompt-audit` for
line-level review of instruction text, which is what version 1 did, so version 2
moves to what the built-in checks do not ask: how the pieces of a setup work
together, and whether each is good at its job.

### Added
- `scripts/measure.py`: lists every piece of a setup, when it loads, its estimated
  context cost, and 30 days of usage by model, tool, skill and agent from local
  session history, including what one run of each subagent type costs and how
  often a session rebuilt its cache and why. `--compare` shows what changed
  between two runs; `--piece` measures one skill or subagent on its own.
- `kb/`: 822 claims from 82 Anthropic sources, each with a verbatim quote, source
  and read date, covering Claude Opus 5.5, Sonnet 5.5, Haiku 5.5 and Fable 5.2.
- `scripts/kb_gate.py`: rejects any claim whose quote is not in its source
  snapshot; after a fetch, this is also how stale claims are found.
- `scripts/kb_fetch.py` and `scripts/kb.py`: fetch sources by content hash, and
  select claims by topic and model for a review.
- `kb/core.json`: for each review question, the dozen claims to read first and
  the principle they support. `kb/harness.json`: the numbers the
  measurement depends on, each tied to the claim that documents it.
- `evals/`: a setup with ten planted defects and a clean one, with an answer
  key, for checking how many defects a review finds and how many it invents.
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
