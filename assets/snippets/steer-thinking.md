# Snippet: steer-thinking

| field | value |
|---|---|
| triggers_rule | AR-REASON-019 |
| applies_to | system_prompt |
| model_specific | opus-4-8, sonnet-5 (thinking default-ON), opus-4-7, opus-4-6, sonnet-4-6 |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-4-8#calibrating-effort-and-thinking-depth |
| insertion_pattern | append when adaptive-thinking model thinks more than desired (large/complex system prompts inflate thinking budget) |
| voice_drift | low |

## When to insert

When AR-REASON-019 fires — adaptive thinking active but no steering language to
suppress on simple queries.

## Verbatim block

```text
Thinking adds latency and should only be used when it will meaningfully improve answer quality — typically for problems that require multi-step reasoning. When in doubt, respond directly.
```

## Operator notes

- Doctrine context: *"The triggering behavior for adaptive thinking is
  steerable. If you find the model thinking more often than you'd like — which
  can happen with large or complex system prompts — add guidance to steer it.
  As always, measure the effect of any prompting changes on performance."*
- Variant for hard latency requirements: lower the `effort` setting first
  (per AR-REASON-010).
