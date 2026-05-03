# Snippet: latex-opt-out

| field | value |
|---|---|
| triggers_rule | (no canonical rule_id; advisory) |
| applies_to | system_prompt |
| model_specific | opus-4-6 (LaTeX default), applicable to 4.7 |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#latex-output |
| insertion_pattern | append when output is rendered in plain-text contexts (terminals, plain TTS, etc.) |
| voice_drift | low |

## When to insert

When the consuming surface cannot render LaTeX (terminal, plain text, simple
markdown viewers without math) and target model defaults to LaTeX.

## Verbatim block

```text
Format your response in plain text only. Do not use LaTeX, MathJax, or any markup notation such as \( \), $, or \frac{}{}. Write all math expressions using standard text characters (e.g., "/" for division, "*" for multiplication, and "^" for exponents).
```

## Operator notes

- Doctrine context: *"Claude Opus 4.6 defaults to LaTeX for mathematical
  expressions, equations, and technical explanations. If you prefer plain text,
  add the following instructions to your prompt."*
- 4.7 inherits 4.6 behavior here unless specified otherwise.
