# Snippet: general-purpose-solution

| field | value |
|---|---|
| triggers_rule | AR-MODEL-012 |
| applies_to | system_prompt, claude_md, agent |
| model_specific | claude-4-family |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#avoid-focusing-on-passing-tests-and-hard-coding |
| insertion_pattern | append when artifact involves test-driven coding without guard against hard-coding |
| voice_drift | low |

## When to insert

When AR-MODEL-012 fires — coding task with tests but no instruction against
test-specific shortcuts.

## Verbatim block

```text
Please write a high-quality, general-purpose solution using the standard tools available. Do not create helper scripts or workarounds to accomplish the task more efficiently. Implement a solution that works correctly for all valid inputs, not just the test cases. Do not hard-code values or create solutions that only work for specific test inputs. Instead, implement the actual logic that solves the problem generally.

Focus on understanding the problem requirements and implementing the correct algorithm. Tests are there to verify correctness, not to define the solution. Provide a principled implementation that follows best practices and software design principles.

If the task is unreasonable or infeasible, or if any of the tests are incorrect, please inform me rather than working around them. The solution should be robust, maintainable, and extendable.
```

## Operator notes

- Doctrine context: *"Claude can sometimes focus too heavily on making tests
  pass at the expense of more general solutions, or may use workarounds like
  helper scripts for complex refactoring instead of using standard tools
  directly."*
