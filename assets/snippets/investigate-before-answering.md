# Snippet: investigate-before-answering

| field | value |
|---|---|
| triggers_rule | AR-MODEL-011 |
| applies_to | system_prompt, claude_md, agent |
| model_specific | claude-4-family |
| verbatim | yes — XML block reproduced from doc |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#minimizing-hallucinations-in-agentic-coding |
| insertion_pattern | append to system prompt or CLAUDE.md when artifact requests code analysis without grounding instruction |
| voice_drift | low |

## When to insert

When AR-MODEL-011 fires — artifact asks for claims about code/files without an
explicit "read first" instruction.

## Verbatim block

```text
<investigate_before_answering>
Never speculate about code you have not opened. If the user references a specific file, you MUST read the file before answering. Make sure to investigate and read relevant files BEFORE answering questions about the codebase. Never make any claims about code before investigating unless you are certain of the correct answer - give grounded and hallucination-free answers.
</investigate_before_answering>
```

## Operator notes

- The all-caps `MUST` is part of Anthropic's canonical wording — preserve it.
- This snippet is type-aware: emphasis is endorsed in system_prompt/claude_md
  (AR-CLAR-015); within a *skill body*, prefer rephrasing as Anthropic-style
  guidance per AR-CC-S09.
