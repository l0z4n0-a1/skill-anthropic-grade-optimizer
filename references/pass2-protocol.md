# Pass 2 Protocol — Qualitative Audit Workflow

Pass 1 (`scripts/pass1_mechanical.py`) handles regex / code-check rules deterministically. Pass 2 handles the rules with `detection_method: llm-judge` or `heuristic` that require reading the artifact.

This document is the **explicit reasoning protocol** for Pass 2. Without it, "reason directly" is hand-waving.

## Inputs

- `<artifact_content>` — the full text of the artifact under audit
- `<artifact_type>` — output of classify_artifact.py
- `<applicable_rules>` — subset from `references/rubric-by-type.yaml` for this type
- `<pass1_findings>` — JSON output from pass1_mechanical.py
- `<target_model>` — for model-specific rule activation

## Workflow (5 steps)

### Step 1: Load context

For each rule with `detection_method: llm-judge` or `heuristic` in `applicable_rules`:

1. Read the rule's full record from `references/rules-anthropic.yaml` (statement, verbatim_quote, source_url, detection_hint).
2. If `model_specific` field exists, check if `target_model` matches. If not, skip the rule.
3. If the rule appears in `false_positive_rules` for this artifact type (rubric-by-type.yaml § false_positive_rules), skip with comment `suppressed-by-D9`.

### Step 2: Apply per-rule reasoning

For each surviving rule, follow this exact structure:

```
RULE: <rule_id>
STATEMENT: <one-line statement>
DETECTION HINT: <from rule record, if present>

EVIDENCE SCAN:
  Read the artifact looking for:
    - Pattern that matches the rule's statement
    - Counter-evidence (rule satisfied)

VERDICT (choose one):
  [ ] HIT — rule violated, finding raised
  [ ] PASS — rule satisfied or not applicable in context
  [ ] AMBIGUOUS — evidence inconclusive; surface as Open Question, NOT a finding

IF HIT:
  - Cite location (line range or section name)
  - Cite verbatim_quote from rule
  - Cite source_url
  - Compute severity → triage (see Severity table in SKILL.md)
  - Estimate score_impact (negative integer)
  - Estimate voice_drift_risk (low/medium/high) of fixing it
```

**Hard rule:** if you cannot identify a specific location or section in the artifact that demonstrates the violation, the verdict is `AMBIGUOUS` not `HIT`. Anthropic-grade means cited or silent (H1).

### Step 3: Apply heuristic categories

Some heuristic rules need quantitative thresholds. Use these defaults (override only with explicit reason):

| Heuristic | Threshold | Action |
|---|---|---|
| AR-CLAR-006 (negative-only without positive alt) | 5+ negatives, <50% paired with positive | HIT |
| AR-CLAR-007 (style mismatch) | prompt heavily markdown, output requested as prose | HIT |
| AR-CONTEXT-004 (context rot risk) | artifact >5000 tokens, no curation strategy | HIT |
| AR-CONTEXT-013 (bloated CLAUDE.md) | >300 lines OR >50% lines repetitive | HIT |
| AR-CC-S05 (skill not concise) | repeats info Claude already knows (e.g., explains what Python is) | HIT |
| AR-AGENT-001 (no stop conditions) | workflow has loops without max-iter | HIT |
| AR-EVAL-001 (no verification embedded) | prompt asks for code/artifact without test/check criterion | HIT |

### Step 4: Severity calibration via target model

Some rules amplify by model. Apply:

- `target_model = opus-4-7`: AR-CLAR-009/010/012, AR-MODEL-002/003/004/005/006, AR-REASON-010 → all SEVERITY one notch UP (soft → hard)
- `target_model = haiku-4-5`: AR-EXAMPLE-004 (3-5 examples) → SEVERITY UP; few-shot is more critical for Haiku
- `target_model = haiku-4-5`: AR-REASON-011 (adaptive thinking) → DROP — not supported on Haiku
- `target_model = sonnet-4-6`: AR-CONTEXT-008 (context awareness) → SEVERITY UP; Sonnet 4.6 supports it

### Step 5: D9 conflict resolution

Two-step check before emitting any finding involving emphasis (ALL-CAPS, IMPORTANT, YOU MUST, NEVER, ALWAYS):

1. Look up artifact_type in `rubric-by-type.yaml` § `false_positive_rules`.
2. If `AR-CC-S09` is suppressed for this type → drop the finding silently. Reason: emphasis is doctrinally endorsed for instruction-style artifacts (CLAUDE.md, system_prompt, user_prompt) per AR-CLAR-015.

If a finding survives D9, include note: "D9-resolved: yellow-flag applies in skill/subagent body context."

## Voice Preservation Heuristic (for diff generation)

When mode = optimize or full, before producing a diff for a finding:

```
1. Identify the operator's voice signature in the artifact:
   - Recurring metaphors / domain language
   - Idiosyncratic structures (e.g., a framework that numbers its laws "L1-L8" or its phases "P0-P5")
   - Tone markers (formal/casual/technical)
   - Length norms

2. For each proposed diff:
   a. Could this change be expressed using the operator's existing vocabulary?
      → Yes: use it.
      → No: estimate voice_drift_increment.
   b. If diff replaces > 30% of original phrasing in the modified region:
      → Flag as HIGH voice_drift_risk
      → Require operator confirmation in Open Questions
   c. If diff conflicts with a recurring authorial pattern:
      → Mark as ⚪ PRESERVE candidate, do not emit diff
      → Add to preservation_log

3. Aggregate voice_drift_score across all proposed diffs:
   total_drift = sum(per_diff_drift) / artifact_total_length
   If total_drift > 0.10: abort optimization run
```

## Diff Generation (mode ≠ audit)

For each 🔴/🟡 finding (and 🟢 only with `--push-ceiling`):

```
DIFF FORMAT:
  --- before (line X-Y of artifact)
  +++ after (proposed)
  @@ context @@
  - <removed line>
  + <added line>
  
  rule_cited: <rule_id>
  source_url: <url>
  verbatim_quote: "<quote>"
  severity: <hard/soft>
  expected_score_delta: +<n>
  voice_drift_estimate: <low/medium/high>
  regression_risk: <low/medium/high>
```

**Surgical principle (H2):** smallest possible change. If the fix needs > 5 lines modified, decompose into multiple smaller diffs.

**Never-rewrite rule:** if a single diff would replace > 40% of the artifact's content, do not emit it. Add Open Question instead: "Major restructuring suggested; defer to operator."

## Open Questions Generation

Surface as Open Questions in the report (verbose mode), not as findings:

- Conflicting rules with no documented resolution (see `references/gaps.md` § conflicts)
- AMBIGUOUS verdicts from Step 2
- High-voice-drift diffs deferred per voice preservation
- Rules with `confidence: low` modulation cells
- Decisions where authorial voice and Anthropic doctrine genuinely disagree

Format:
```
OPEN QUESTIONS:
1. [Q-001] <one-sentence question>
   Context: <why this is ambiguous>
   Options: (a) <option>, (b) <option>
   Default if no answer: <conservative choice>
```

## Output

Pass 2 emits a JSON appendix to merge with Pass 1 findings:

```json
{
  "pass": "qualitative (pass 2)",
  "findings_count": <n>,
  "findings": [...],
  "open_questions": [...],
  "preservation_log": [...],
  "rules_evaluated": <n>,
  "rules_skipped_model_mismatch": <n>,
  "rules_skipped_d9": <n>,
  "verdicts": {"HIT": <n>, "PASS": <n>, "AMBIGUOUS": <n>}
}
```

## Coverage Honesty

Pass 2 cannot guarantee 100% rule coverage on a single execution. Anthropic engineer would expect:

- Top zero-tolerance rules (`rules-master.yaml § zero_tolerance_ids`): always evaluated
- Type-applicable hard rules: always evaluated
- Type-applicable soft rules: evaluated unless time-budget mode (`--fast`) limits
- All AMBIGUOUS results surfaced as Open Questions, not silently dropped

Report must declare in coverage_caveat:
```
PASS 2 COVERAGE
  Rules evaluated: <n> / <total_applicable>
  Reason for any skips: <list>
  Confidence in non-fired rules: <high/medium/low>
```
