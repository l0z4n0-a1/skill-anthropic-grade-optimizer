# Contributing

Thanks for the interest. The skill ships under tight discipline; contributions
are welcome that respect the same rules the auditor enforces.

## The non-negotiables

1. **Cite or stay silent.** Every new rule in `references/rules-anthropic.yaml`
   must carry a `source_url` pointing to live Anthropic documentation and a
   `verbatim_quote` lifted byte-for-byte from that source. PRs adding rules
   without both will be closed.
2. **Artifact type comes first.** Detection rules live in
   `references/rubric-by-type.yaml`. A new rule must declare which artifact
   types it applies to and which (if any) it must be suppressed on as a
   false positive.
3. **Voice drift trumps score.** Optimizations and snippet patches must not
   rewrite the operator's voice. If a snippet is cosmetic, it does not
   belong in `assets/snippets/`.

## Local setup

```bash
git clone https://github.com/l0z4n0-a1/skill-anthropic-grade-optimizer.git
cd anthropic-grade-optimizer
pip install pyyaml pytest
```

Optional, for `--pass2`:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

## The full gate (must pass before opening a PR)

```bash
python scripts/check_model_currency.py
python -m pytest tests/ -v -p no:langsmith_plugin
python scripts/run_eval_suite.py
python tests/calibration.py
python scripts/run.py SKILL.md --target opus-4-7 --mode audit
```

The CI workflow (`.github/workflows/ci.yml`) runs all five on every push and
PR. PRs that fail any gate will not be merged.

## Adding a rule

1. **Add to SSOT.** Append to `references/rules-anthropic.yaml`:

   ```yaml
   - rule_id: AR-<DIM>-<NNN>
     dimension: D-<DIM>
     severity: hard | soft | medium | low
     detection_method: regex | code-check | heuristic | hybrid | llm-judge
     source_url: https://...                  # live Anthropic doc
     verbatim_quote: "..."                    # byte-for-byte
     applies_to: [skill, claude_md, ...]      # artifact types
   ```

2. **Wire detection.** Add the regex / heuristic to
   `scripts/pass1_mechanical.py` (or document the qualitative criteria in
   `references/pass2-protocol.md` for `llm-judge`).

3. **Add a fixture.** Drop a violating example in `evals/fixtures/` and an
   expected entry in `evals/ground-truth.yaml`.

4. **Add a unit test.** `tests/test_rule_schema.py` is parametrized over every
   `rule_id` — your rule will be picked up automatically. Add detector
   coverage to `tests/test_pass1_detectors.py` if you wired a new detector
   branch.

5. **Run the gate** and update the score timeline in `evals/SELF-AUDIT.md`
   if the change moves any number.

## Adding a model profile

Edit `references/modulation-matrix.yaml`. Then add the model ID to
`KNOWN_CURRENT_MODELS` in `scripts/check_model_currency.py` so CI starts
guarding against future drift.

## Adding a snippet

Snippets in `assets/snippets/` are byte-for-byte verbatim insertions. Each
must:

- Carry a header table with `triggers_rule`, `applies_to`, `model_specific`,
  `source_url`, `insertion_pattern`, `voice_drift`.
- Be registered in `assets/snippets/index.yaml` under the rule_id that
  consumes it.
- Be type-aware — never patch artifact types it does not apply to.

## Style

- **Python:** PEP 8, type hints where they clarify intent, no docstrings
  that re-state the function name.
- **Markdown:** prefer positive framing; avoid negation-only instructions.
- **Commit messages:** imperative mood, scope prefix
  (`rules:`, `detectors:`, `evals:`, `tests:`, `docs:`, `ci:`).

## Reporting bugs

If the skill misclassifies, hallucinates a rule, or scores something wrong,
attach the artifact (or a minimal repro) and the bundle JSON
(`evals/results/<artifact>.bundle.json`).
