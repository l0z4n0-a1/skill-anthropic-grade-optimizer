# Snippet: concise-output

| field | value |
|---|---|
| triggers_rule | AR-CLAR-016 |
| applies_to | system_prompt, user_prompt |
| model_specific | opus-4-8, sonnet-5, opus-4-7 |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-4-8#response-length-and-verbosity |
| insertion_pattern | append when product depends on shorter outputs and task-calibrated default verbosity is too long |
| voice_drift | low |

## When to insert

When AR-CLAR-016 fires — task-calibrated verbosity (Opus 4.8 / Sonnet 5 / 4.7)
produces longer outputs than the product surface can handle.

## Verbatim block

```text
Provide concise, focused responses. Skip non-essential context, and keep examples minimal.
```

## Operator notes

- Doctrine context (2026-07-11): *"Claude Opus 4.8 calibrates response length to how complex
  it judges the task to be, rather than defaulting to a fixed verbosity. This
  usually means shorter answers on simple lookups and much longer ones on
  open-ended analysis. If your product depends on a certain style or verbosity
  of output, you may need to tune your prompts."*
- If verbosity is task-specific (over-explaining particular sections), prefer
  positive examples of desired concision over negative instructions per
  AR-CLAR-008.
