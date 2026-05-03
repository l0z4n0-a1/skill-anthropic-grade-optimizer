# Snippet: pick-and-commit

| field | value |
|---|---|
| triggers_rule | AR-REASON-009 |
| applies_to | system_prompt, claude_md |
| model_specific | opus-4-6 (also useful 4.7 in agentic loops) |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#overthinking-and-excessive-thoroughness |
| insertion_pattern | append when artifact triggers thrash (revisits decisions, oscillates between approaches) |
| voice_drift | low |

## When to insert

When AR-REASON-009 fires — long agentic loop or analysis prompt without
commitment language; model risks overthinking and decision-revisiting.

## Verbatim block

```text
When you're deciding how to approach a problem, choose an approach and commit to it. Avoid revisiting decisions unless you encounter new information that directly contradicts your reasoning. If you're weighing two approaches, pick one and see it through. You can always course-correct later if the chosen approach fails.
```

## Operator notes

- Doctrine context: *"Claude Opus 4.6 may think extensively, which can inflate
  thinking tokens and slow down responses. If this behavior is undesirable, you
  can add explicit instructions to constrain its reasoning."*
- Useful complement to lowering `effort` parameter when latency is critical.
