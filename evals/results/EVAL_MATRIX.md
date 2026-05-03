# Eval Matrix — Anthropic-Grade Optimizer v1.0

Run date: 2026-05-02 | Pass rate: 15/15

| Fixture | Category | Score | Grade | Expected | Hard | Findings | PASS |
|---|---|---|---|---|---|---|---|
| bad-skill.md | bad | 45.0 | F | F | 3 | 5 | PASS |
| bad-claude-md.md | bad | 47.0 | F | F | 3 | 6 | PASS |
| bad-subagent.md | bad | 44.0 | F | F | 2 | 4 | PASS |
| bad-hook.json | bad | 77.0 | C | C | 1 | 2 | PASS |
| bad-mcp.json | bad | 42.0 | F | F | 2 | 3 | PASS |
| good-skill.md | good | 100.0 | A | A | 0 | 0 | PASS |
| good-claude-md.md | good | 100.0 | A | A | 0 | 0 | PASS |
| good-subagent.md | good | 100.0 | A | A | 0 | 0 | PASS |
| good-hook.json | good | 100.0 | A | A | 0 | 0 | PASS |
| good-mcp.json | good | 100.0 | A | A | 0 | 0 | PASS |
| adversarial-minimal-skill.md | adversarial | 98.0 | A | A | 0 | 1 | PASS |
| adversarial-minimal-claude-md.md | adversarial | 100.0 | A | A | 0 | 0 | PASS |
| adversarial-minimal-subagent.md | adversarial | 93.0 | A | A | 0 | 1 | PASS |
| cross-bad-skill.md | cross | 39.0 | F-- | F or F-- | 3 | 6 | PASS |
| cross-bad-subagent.md | cross | 37.0 | F-- | F or F-- | 2 | 5 | PASS |

## Per-Category Pass Rate

- **adversarial**: 3/3
- **bad**: 5/5
- **cross**: 2/2
- **good**: 5/5
