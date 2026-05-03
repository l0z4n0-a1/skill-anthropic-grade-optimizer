# Snippet: subagent-spawning-4-7

| field | value |
|---|---|
| triggers_rule | AR-MODEL-015 |
| applies_to | system_prompt, agent, claude_md |
| model_specific | opus-4-7 |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#controlling-subagent-spawning |
| insertion_pattern | append to artifacts that orchestrate subagents on Opus 4.7 (do NOT insert into subagent files themselves) |
| voice_drift | low |

## When to insert

When AR-MODEL-015 fires — orchestrator artifact mentions subagents/Task() but
lacks guidance on when to spawn vs. work directly.

## Verbatim block

```text
Do not spawn a subagent for work you can complete directly in a single response (e.g. refactoring a function you can already see).

Spawn multiple subagents in the same turn when fanning out across items or reading multiple files.
```

## Operator notes

- Doctrine context: *"Claude Opus 4.7 tends to spawn fewer subagents by default.
  However, this behavior is steerable through prompting; give Claude Opus 4.7
  explicit guidance around when subagents are desirable."*
- Type-aware guard: NEVER insert into a subagent file (`.claude/agents/<name>.md`).
  AR-CC-043 forbids subagents from spawning subagents; this guidance would be
  nonsensical there.
