# Snippet: code-review-coverage

| field | value |
|---|---|
| triggers_rule | AR-MODEL-018 |
| applies_to | system_prompt, skill (code-review domain) |
| model_specific | opus-4-7 |
| verbatim | yes — copied byte-for-byte from doc |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#code-review-harnesses |
| insertion_pattern | replace any "be conservative" / "only high-severity" / "don't nitpick" phrasing in code-review system prompts |
| voice_drift | low (Anthropic-canonical wording) |

## When to insert

When AR-MODEL-018 fires (target=opus-4-7, code-review prompt contains recall-killing
phrases like "only high-severity", "be conservative", "don't nitpick").

## Verbatim block

```text
Report every issue you find, including ones you are uncertain about or consider low-severity. Do not filter for importance or confidence at this stage - a separate verification step will do that. Your goal here is coverage: it is better to surface a finding that later gets filtered out than to silently drop a real bug. For each finding, include your confidence level and an estimated severity so a downstream filter can rank them.
```

## Operator notes

- Doctrine quote on regression: *"When a review prompt says things like 'only report
  high-severity issues,' 'be conservative,' or 'don't nitpick,' Claude Opus 4.7 may
  follow that instruction more faithfully than earlier models did — it may investigate
  the code just as thoroughly, identify the bugs, and then not report findings it
  judges to be below your stated bar. This can show up as the model doing the same
  depth of investigation but converting fewer investigations into reported findings,
  especially on lower-severity bugs. Precision typically rises, but measured recall
  can fall even though the model's underlying bug-finding ability has improved."*
- If your harness has a separate verification/dedup/ranking stage, tell the model
  explicitly that its job at the finding stage is *coverage*.
- If single-pass self-filter is required, replace qualitative bars ("important")
  with concrete ones: *"report any bugs that could cause incorrect behavior, a test
  failure, or a misleading result; only omit nits like pure style or naming
  preferences."*
