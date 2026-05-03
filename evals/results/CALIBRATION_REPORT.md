# Calibration Report — anthropic-grade-optimizer

**Date:** auto-generated | **Fixtures:** 15 | **Overall accuracy:** 93.3% | **Macro-F1:** 0.641

## Per-class metrics

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| A | 1.000 | 1.000 | 1.000 | 8 |
| C | 0.000 | 0.000 | 0.000 | 0 |
| F | 1.000 | 0.857 | 0.923 | 7 |

## Confusion matrix

Rows = true label, columns = predicted grade.

| true \\ pred | A | C | F |
|---|---|---|---|
| **A** | 8 | 0 | 0 |
| **F** | 0 | 1 | 6 |

## Per-fixture breakdown

| Fixture | Category | True | Pred | Score | Match | Findings (act/exp) |
|---|---|---|---|---|---|---|
| bad-skill.md | bad | F | F | 45.0 | ✓ | 5/4 |
| bad-claude-md.md | bad | F | F | 47.0 | ✓ | 6/6 |
| bad-subagent.md | bad | F | F | 44.0 | ✓ | 4/3 |
| bad-hook.json | bad | F | C | 77.0 | ✗ | 2/2 |
| bad-mcp.json | bad | F | F | 42.0 | ✓ | 3/3 |
| good-skill.md | good | A | A | 100.0 | ✓ | 0/1 |
| good-claude-md.md | good | A | A | 100.0 | ✓ | 0/1 |
| good-subagent.md | good | A | A | 100.0 | ✓ | 0/1 |
| good-hook.json | good | A | A | 100.0 | ✓ | 0/0 |
| good-mcp.json | good | A | A | 100.0 | ✓ | 0/0 |
| adversarial-minimal-skill.md | adversarial | A | A | 98.0 | ✓ | 1/1 |
| adversarial-minimal-claude-md.md | adversarial | A | A | 100.0 | ✓ | 0/0 |
| adversarial-minimal-subagent.md | adversarial | A | A | 93.0 | ✓ | 1/1 |
| cross-bad-skill.md | cross | F | F | 39.0 | ✓ | 6/6 |
| cross-bad-subagent.md | cross | F | F | 37.0 | ✓ | 5/3 |

## Finding-count drift

| Fixture | Expected | Actual | Delta |
|---|---|---|---|
| bad-skill.md | 4 | 5 | +1 |
| bad-claude-md.md | 6 | 6 | +0 |
| bad-subagent.md | 3 | 4 | +1 |
| bad-hook.json | 2 | 2 | +0 |
| bad-mcp.json | 3 | 3 | +0 |
| good-skill.md | 1 | 0 | -1 |
| good-claude-md.md | 1 | 0 | -1 |
| good-subagent.md | 1 | 0 | -1 |
| good-hook.json | 0 | 0 | +0 |
| good-mcp.json | 0 | 0 | +0 |
| adversarial-minimal-skill.md | 1 | 1 | +0 |
| adversarial-minimal-claude-md.md | 0 | 0 | +0 |
| adversarial-minimal-subagent.md | 1 | 1 | +0 |
| cross-bad-skill.md | 6 | 6 | +0 |
| cross-bad-subagent.md | 3 | 5 | +2 |

## Interpretation

- **Macro-F1 < 0.85** — scorer needs calibration. Inspect false positives/negatives.