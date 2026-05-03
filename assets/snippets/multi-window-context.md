# Snippet: multi-window-context

| field | value |
|---|---|
| triggers_rule | AR-CONTEXT-009 |
| applies_to | system_prompt, agent |
| model_specific | sonnet-4-6, sonnet-4-5, haiku-4-5 (context-aware) |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#context-awareness-and-multi-window-workflows |
| insertion_pattern | append when agent runs in compacting harness (Claude Code, long-running pipelines) |
| voice_drift | low |

## When to insert

When AR-CONTEXT-009 fires — agentic prompt without compaction-awareness language
and target model has context-awareness capability.

## Verbatim block

```text
Your context window will be automatically compacted as it approaches its limit, allowing you to continue working indefinitely from where you left off. Therefore, do not stop tasks early due to token budget concerns. As you approach your token budget limit, save your current progress and state to memory before the context window refreshes. Always be as persistent and autonomous as possible and complete tasks fully, even if the end of your budget is approaching. Never artificially stop any task early regardless of the context remaining.
```

## Operator notes

- Doctrine context: *"Claude 4.6 and Claude 4.5 models feature context awareness,
  enabling the model to track its remaining context window throughout a
  conversation."*
- For non-context-aware models (Opus 4.7), the prompt still works but
  benefits less.
