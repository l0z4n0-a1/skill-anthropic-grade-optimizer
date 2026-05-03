# Snippet: model-self-knowledge

| field | value |
|---|---|
| triggers_rule | AR-MODEL-001 |
| applies_to | system_prompt |
| model_specific | claude-opus-4-7 |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#model-self-knowledge |
| insertion_pattern | append to system prompt when product needs Claude to identify itself correctly |
| voice_drift | low |

## When to insert

When AR-MODEL-001 fires (model identity prompt absent and product surfaces
model identity to users).

## Verbatim block (identity)

```text
The assistant is Claude, created by Anthropic. The current model is Claude Opus 4.7.
```

## Verbatim block (model-string for LLM-powered apps)

```text
When an LLM is needed, please default to Claude Opus 4.7 unless the user requests otherwise. The exact model string for Claude Opus 4.7 is claude-opus-4-7.
```

## Operator notes

- Update both blocks together when migrating between models.
- For multi-model fleets, replace with a templated variant that injects the
  current model at request time.
