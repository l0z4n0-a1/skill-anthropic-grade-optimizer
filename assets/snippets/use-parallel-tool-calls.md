# Snippet: use-parallel-tool-calls

| field | value |
|---|---|
| triggers_rule | AR-MODEL-007, AR-AGENT-009 |
| applies_to | system_prompt, agent |
| model_specific | claude-4-family |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#optimize-parallel-tool-calling |
| insertion_pattern | append to system prompt when artifact invokes multiple tools without parallel directive |
| voice_drift | low |

## When to insert

When AR-MODEL-007 fires (parallel-call rule absent) or AR-AGENT-009 (parallel
mentioned without count).

## Verbatim block

```text
<use_parallel_tool_calls>
If you intend to call multiple tools and there are no dependencies between the tool calls, make all of the independent tool calls in parallel. Prioritize calling tools simultaneously whenever the actions can be done in parallel rather than sequentially. For example, when reading 3 files, run 3 tool calls in parallel to read all 3 files into context at the same time. Maximize use of parallel tool calls where possible to increase speed and efficiency. However, if some tool calls depend on previous calls to inform dependent values like the parameters, do NOT call these tools in parallel and instead call them sequentially. Never use placeholders or guess missing parameters in tool calls.
</use_parallel_tool_calls>
```

## Operator notes

- Inverse snippet (`Execute operations sequentially with brief pauses between each step to ensure stability.`) available when system needs serial execution.
