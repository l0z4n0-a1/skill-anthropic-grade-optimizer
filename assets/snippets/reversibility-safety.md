# Snippet: reversibility-safety

| field | value |
|---|---|
| triggers_rule | AR-MODEL-009 |
| applies_to | system_prompt, agent, claude_md |
| model_specific | claude-4-family (esp. 4.6, 4.7) |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#balancing-autonomy-and-safety |
| insertion_pattern | append when agent has filesystem/git/network access without confirmation guardrail |
| voice_drift | low |

## When to insert

When AR-MODEL-009 fires — agentic prompt grants destructive capabilities without
guidance on reversibility.

## Verbatim block

```text
Consider the reversibility and potential impact of your actions. You are encouraged to take local, reversible actions like editing files or running tests, but for actions that are hard to reverse, affect shared systems, or could be destructive, ask the user before proceeding.

Examples of actions that warrant confirmation:
- Destructive operations: deleting files or branches, dropping database tables, rm -rf
- Hard to reverse operations: git push --force, git reset --hard, amending published commits
- Operations visible to others: pushing code, commenting on PRs/issues, sending messages, modifying shared infrastructure

When encountering obstacles, do not use destructive actions as a shortcut. For example, don't bypass safety checks (e.g. --no-verify) or discard unfamiliar files that may be in-progress work.
```

## Operator notes

- Pair with project-specific allowlist of "auto-OK" actions (per
  AR-CC-066 — hooks for hard guarantees).
