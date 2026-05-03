# Snippet: avoid-overengineering

| field | value |
|---|---|
| triggers_rule | AR-MODEL-010 |
| applies_to | system_prompt, claude_md |
| model_specific | opus-4-5, opus-4-6 (also useful on 4.7) |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#overeagerness |
| insertion_pattern | append when artifact triggers excess scaffolding / abstractions / unrequested features |
| voice_drift | low |

## When to insert

When AR-MODEL-010 fires — artifact lacks scope-discipline language and target
model is 4.5/4.6/4.7 (all known to overengineer without constraint).

## Verbatim block

```text
Avoid over-engineering. Only make changes that are directly requested or clearly necessary. Keep solutions simple and focused:

- Scope: Don't add features, refactor code, or make "improvements" beyond what was asked. A bug fix doesn't need surrounding code cleaned up. A simple feature doesn't need extra configurability.

- Documentation: Don't add docstrings, comments, or type annotations to code you didn't change. Only add comments where the logic isn't self-evident.

- Defensive coding: Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code and framework guarantees. Only validate at system boundaries (user input, external APIs).

- Abstractions: Don't create helpers, utilities, or abstractions for one-time operations. Don't design for hypothetical future requirements. The right amount of complexity is the minimum needed for the current task.
```

## Operator notes

- Doctrine context: *"Claude Opus 4.5 and Claude Opus 4.6 have a tendency to
  overengineer by creating extra files, adding unnecessary abstractions, or
  building in flexibility that wasn't requested."*
- Equally applicable to 4.7 in autonomous coding contexts.
