# Snippet: do-not-act-before-instructions

| field | value |
|---|---|
| triggers_rule | AR-CLAR-011 (inverse posture) |
| applies_to | system_prompt |
| model_specific | claude-4-family |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#tool-usage |
| insertion_pattern | use when product needs Claude to research/recommend before editing |
| voice_drift | low |

## When to insert

When the artifact wants Claude to be hesitant by default — research/recommend
before action, never edit on ambiguity.

## Verbatim block

```text
<do_not_act_before_instructions>
Do not jump into implementatation or changes files unless clearly instructed to make changes. When the user's intent is ambiguous, default to providing information, doing research, and providing recommendations rather than taking action. Only proceed with edits, modifications, or implementations when the user explicitly requests them.
</do_not_act_before_instructions>
```

## Operator notes

- Verbatim preserves the doc's typo "implementatation" — do not "fix" it.
- Inverse of `default-to-action.md`; choose one based on product posture.
