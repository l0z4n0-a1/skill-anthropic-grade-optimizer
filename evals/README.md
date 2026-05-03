# Eval Suite — Anthropic-Grade Optimizer

15 hand-crafted fixtures covering all 7 supported artifact types across 4 categories
(`good`, `bad`, `adversarial-minimal`, `cross`). Each fixture has a documented
expected score range in `ground-truth.yaml`; the suite passes when every fixture
lands inside its range.

## Run the suite

```bash
python scripts/run_eval_suite.py
```

Emits `evals/results/EVAL_MATRIX.md` (PASS/FAIL per fixture) and per-fixture
bundle JSON. The CI workflow runs this on every push.

## Run a single fixture manually

```bash
python scripts/run.py evals/fixtures/bad-skill.md --target opus-4-7 --mode audit
```

## Calibration telemetry

```bash
python tests/calibration.py
```

Produces `evals/results/CALIBRATION_REPORT.md` with per-class precision / recall / F1
and a confusion matrix vs `ground-truth.yaml`. Exits non-zero when overall accuracy
drops below 85%.

## Strange-loop self-audit

```bash
python scripts/run.py SKILL.md --target opus-4-7 --mode audit
```

The skill audits its own `SKILL.md` with itself. The committed result lives in
[`SELF-AUDIT.md`](SELF-AUDIT.md) and re-runs on every CI build.

## Fixture inventory

| Category | Count | Purpose |
|---|---|---|
| `good-*` | 5 | Reference exemplars — should score A (≥85). |
| `bad-*` | 5 | Deliberate violations — should score F or near-F. |
| `adversarial-minimal-*` | 3 | Sparse-but-correct — should NOT be over-flagged for size. |
| `cross-bad-*` | 2 | Type-confusion bait — should NOT fire SKILL rules on subagents and vice versa (false-positive suppression matrix). |

## Adding a fixture

1. Drop the artifact in `evals/fixtures/`.
2. Add an entry to `evals/ground-truth.yaml` with `expected_grade` and `score_range`.
3. Add the rule_id to `tests/test_pass1_detectors.py` if a new detector path is exercised.
4. Run `python scripts/run_eval_suite.py` and `python tests/calibration.py` to confirm.
