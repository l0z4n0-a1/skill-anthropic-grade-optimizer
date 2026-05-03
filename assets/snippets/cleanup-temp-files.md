# Snippet: cleanup-temp-files

| field | value |
|---|---|
| triggers_rule | (no canonical rule_id; advisory) |
| applies_to | system_prompt, agent |
| model_specific | claude-4-family (esp. 4.5/4.6/4.7) |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#reduce-file-creation-in-agentic-coding |
| insertion_pattern | append when agentic coding workflow should not leave scratch files |
| voice_drift | low |

## When to insert

When the workflow uses Python scratch files for iteration but the consumer
doesn't want them persisted.

## Verbatim block

```text
If you create any temporary new files, scripts, or helper files for iteration, clean up these files by removing them at the end of the task.
```

## Operator notes

- Doctrine context: *"Claude's latest models may sometimes create new files for
  testing and iteration purposes... Using temporary files can improve outcomes
  particularly for agentic coding use cases."*
- Don't use this snippet if the workflow legitimately benefits from persistent
  scratch files (long-running pipelines, multi-window workflows per
  AR-CONTEXT-009).
