# Scripts, Assets & Validation — detailed map

> Moved from SKILL.md tail (poda 2026-07-02) to keep the body under budget. The body
> keeps a 1-line-per-file index pointing here; load this file when you need script
> arguments, snippet coverage detail, or the validation pipeline explanation.

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
- `worked-examples.md` — 2 extra worked examples + the golden's negative twin.
- `scripts-and-assets-map.md` — this file.

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

**Note on `tests/` and `evals/` (poda 2026-07-02):** this skill directory is the
working tree of a separately-versioned, published GitHub repo
(`l0z4n0-a1/skill-anthropic-grade-optimizer`) with its own CI
(`.github/workflows/ci.yml`) that runs `pytest tests/`, `scripts/run_eval_suite.py`,
and `tests/calibration.py` by relative path from the repo root. `tests/` and
`evals/` were NOT relocated during this pruning pass — moving them would break the
wired CI pipeline and desync the git working tree from its own repository
structure. Only `__pycache__/` and `.pytest_cache/` (gitignored, fully
regenerable, zero pointers) were archived to
`~/.claude/archive/skill-dev-artifacts-2026-07-02/anthropic-grade-optimizer/`.
