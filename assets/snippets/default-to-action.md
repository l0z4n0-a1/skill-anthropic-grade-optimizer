# Snippet: default-to-action

| field | value |
|---|---|
| triggers_rule | AR-CLAR-011 |
| applies_to | system_prompt |
| model_specific | claude-4-family |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#tool-usage |
| insertion_pattern | append when artifact uses suggestion-form language ("can you suggest", "would you consider") instead of action-form |
| voice_drift | low |

## When to insert

When AR-CLAR-011 fires (vague action language) and intent is for Claude to *act*,
not just propose.

## Verbatim block

```text
<default_to_action>
By default, implement changes rather than only suggesting them. If the user's intent is unclear, infer the most useful likely action and proceed, using tools to discover any missing details instead of guessing. Try to infer the user's intent about whether a tool call (e.g., file edit or read) is intended or not, and act accordingly.
</default_to_action>
```

## Operator notes

- Pair with AR-CLAR-011 fix that rewrites "can you suggest changes" → "Make these changes".
- Inverse snippet at `do-not-act-before-instructions.md` for conservative posture.
