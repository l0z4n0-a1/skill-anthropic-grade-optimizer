# anthropic-grade-optimizer

[![CI](https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer/actions/workflows/ci.yml)
[![Self-audit](https://img.shields.io/badge/self--audit-98%2F100-brightgreen)](evals/SELF-AUDIT.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](CHANGELOG.md)

> **Cite or stay silent. Artifact type comes first. Voice drift trumps score.**
> An auditor for Claude-directing artifacts against 189 cited Anthropic rules across 11 dimensions, calibrated per model. Every finding ships with verbatim quote and source URL. Authorial voice is preserved by contract — not by accident.

## Why this exists

Most prompt linters score what's *easy to count* and call it a day. This one starts from a different premise: **a Claude-directing artifact is a cognitive contract, not a configuration file.** Audit it like a contract — cite the clause, name the violation, propose the patch, and never rewrite the author into someone else. If the auditor cannot point to the doctrine, the auditor stays silent.

That is the line this skill refuses to cross, and the reason it audits itself on every release.

## The Three Laws

Every finding, every diff, every score lives under these three rules. Violating any one collapses the others.

1. **Cite or stay silent.** Every 🔴 / 🟡 finding carries a `source_url` and a verbatim quote. No source → no finding.
2. **Artifact type comes first.** A SKILL.md rule fired against a CLAUDE.md is a false positive, not a finding. The rubric is type-aware before it is severity-aware.
3. **Voice drift trumps score.** An optimization that lifts the score by diluting the operator's voice is a regression in disguise. Drift over 10% aborts; with `--push-ceiling` the gate tightens to 5%.

## What it does

Reads any Claude-directing artifact — `CLAUDE.md`, `SKILL.md`, subagent, hook, MCP config, system prompt, user prompt, workflow, or `api_config` — and emits:

- a 0–100 score with letter grade
- per-dimension breakdown across the 11 dimensions (D-CLAR, D-STRUCT, D-EXAMPLE, D-REASON, D-CONTEXT, D-MODEL, D-AGENT, D-EVAL, D-TOOL, D-VISION, D-CC for the Claude Code ecosystem)
- triaged findings (🔴 must-fix, 🟡 should-fix, 🟢 may-fix, ❓ open question, ⚪ preserve)
- surgical diffs (mode ≠ audit), each citing the rule that triggered them
- voice-fidelity gate (drift > 10% aborts optimization)
- declared-exception ledger with side-by-side raw/active scores

## Install

**As a Claude Code skill (recommended):**

```bash
git clone https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer.git \
  ~/.claude/skills/anthropic-grade-optimizer
cd ~/.claude/skills/anthropic-grade-optimizer
pip install pyyaml                 # required
pip install anthropic              # optional, only for --pass2
```

The skill auto-loads in any Claude Code session. Trigger it by asking Claude
to "audit this CLAUDE.md", "make this skill Anthropic-grade", "is this
prompt good for Opus 4.7?", etc.

**As a standalone CLI** (no Claude Code required):

```bash
git clone https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer.git
cd anthropic-grade-optimizer
pip install pyyaml
python scripts/run.py path/to/SKILL.md --target opus-4-7 --mode audit
```

**Requirements:** Python 3.10+. `pyyaml` is the only mandatory dependency.
The `anthropic` SDK is only needed for the `--pass2` qualitative-judge mode
and degrades gracefully when absent.

## Quick start

```bash
python scripts/run.py <artifact_path> --target opus-4-7 --mode audit
```

With Pass-2 qualitative audit (requires `ANTHROPIC_API_KEY`):

```bash
python scripts/run.py <artifact_path> --target opus-4-7 --pass2
```

Strict mode (no operator-declared exceptions):

```bash
python scripts/run.py <artifact_path> --target opus-4-7 --no-exceptions
```

Generate diffs and write to a sibling `<artifact>.optimized.<ext>`:

```bash
python scripts/run.py <artifact_path> --target opus-4-7 --mode optimize --apply
```

## How it's verified

| Layer | What it covers | Run |
|---|---|---|
| **Strange-loop self-audit** | Skill audits its own SKILL.md every release | `python scripts/run.py SKILL.md --target opus-4-7` |
| **Eval suite** | 15 fixtures across good / bad / adversarial / cross-bad | `python scripts/run_eval_suite.py` |
| **Unit tests** | Rule-schema integrity (one test per rule_id), detector output shape, orchestrator contract | `python -m pytest tests/ -p no:langsmith_plugin` |
| **Calibration** | Precision / recall / F1 vs ground truth | `python tests/calibration.py` |
| **Model currency** | CI fails when modulation-matrix drifts from known-current models | `python scripts/check_model_currency.py` |
| **CI** | All of the above on every PR | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |

## Honest scope

- **What it does:** audits *prompts and Claude-directing artifacts* against published Anthropic doctrine.
- **What it does not:** evaluate Claude's *responses* (use eval pipelines), or audit application code that consumes the API beyond the prompts themselves.
- **Doctrine limits:** see [`references/gaps.md`](references/gaps.md) for declared coverage gaps. Anthropic doctrine is prescriptive, not diagnostic; the 11-dimension rubric is auditor-canonical, not Anthropic-canonical.

Coverage that cannot be cited is held back, not invented. Silent gaps are worse than declared ones — so we declare them.

## A note on the skill's own name

The skill is named `anthropic-grade-optimizer` even though Anthropic's own
SKILL guidance reserves the word `anthropic` in skill names. This is a
**declared exception** registered in
[`scripts/run.py § DECLARED_EXCEPTIONS`](scripts/run.py): the name is the
most precise descriptor of the skill's purpose, the rule continues to fire
on every self-audit, and the orchestrator always shows both `active` (with
the exception) and `raw` (`--no-exceptions`) scores side by side. Voice
fidelity over hidden adjustment — see [`evals/SELF-AUDIT.md`](evals/SELF-AUDIT.md).

## Architecture

```
SKILL.md                     ← canonical entry point
scripts/
  run.py                     ← orchestrator: classify → pass1 → [pass2] → score → emit
  classify_artifact.py       ← detect type + signals
  pass1_mechanical.py        ← regex / code-check / heuristic detectors
  pass2_executor.py          ← Claude API qualitative judge with prompt caching
  score_calculator.py        ← per-dimension aggregation + voice-drift estimate
  optimize.py                ← surgical diffs + snippet patches
  check_model_currency.py    ← CI guard against modulation-matrix drift
  run_eval_suite.py          ← replay 15 ground-truth fixtures
references/
  rules-anthropic.yaml       ← 189 rules with verbatim_quote + source_url (SSOT)
  rules-master.yaml          ← dimension index
  modulation-matrix.yaml     ← 4 model profiles
  rubric-by-type.yaml        ← rule subsets per artifact type
  pass2-protocol.md          ← qualitative audit protocol
  gaps.md                    ← declared doctrinal limits + 5 resolved conflicts
  anti-patterns.md           ← AP-1..15
  heuristics.md              ← H1..12
  quotes-canonical.md        ← citation library
assets/snippets/             ← 18 verbatim canonical insertions for high-leverage rules
tests/
  test_rule_schema.py        ← one test per rule_id
  test_pass1_detectors.py    ← detector output well-formedness per fixture
  test_orchestrator.py       ← bundle contract, alias compat, exception toggle
  calibration.py             ← precision / recall / F1 vs ground truth
evals/
  fixtures/                  ← 15 ground-truth inputs
  ground-truth.yaml          ← expected scores + grades
  SELF-AUDIT.md              ← committed strange-loop result
  results/                   ← auto-generated EVAL_MATRIX.md, CALIBRATION_REPORT.md
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: every new finding
needs a verbatim Anthropic quote with source URL, and every new rule must
include a fixture and a unit test.

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE).

---

*Shipped under the discipline it audits. The strange-loop closes cleanly: this skill audits itself with the same pipeline it audits everything else, and the result is committed at [`evals/SELF-AUDIT.md`](evals/SELF-AUDIT.md) on every release.*

> *Identity before architecture. Coherence before completeness. Form demonstrates content.*
