# Snippet: avoid-excessive-markdown

| field | value |
|---|---|
| triggers_rule | AR-STRUCT-009 |
| applies_to | system_prompt |
| model_specific | claude-4-family |
| verbatim | yes |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#control-the-format-of-responses |
| insertion_pattern | append when output should be flowing prose, not bullet-fragmented |
| voice_drift | low |

## When to insert

When the desired output is long-form prose (reports, analyses, explanations) but
the model defaults to heavy markdown / bulleted fragments.

## Verbatim block

```text
<avoid_excessive_markdown_and_bullet_points>
When writing reports, documents, technical explanations, analyses, or any long-form content, write in clear, flowing prose using complete paragraphs and sentences. Use standard paragraph breaks for organization and reserve markdown primarily for `inline code`, code blocks (```...```), and simple headings (###, and ###). Avoid using **bold** and *italics*.

DO NOT use ordered lists (1. ...) or unordered lists (*) unless : a) you're presenting truly discrete items where a list format is the best option, or b) the user explicitly requests a list or ranking

Instead of listing items with bullets or numbers, incorporate them naturally into sentences. This guidance applies especially to technical writing. Using prose instead of excessive formatting will improve user satisfaction. NEVER output a series of overly short bullet points.

Your goal is readable, flowing text that guides the reader naturally through ideas rather than fragmenting information into isolated points.
</avoid_excessive_markdown_and_bullet_points>
```

## Operator notes

- Verbatim preserves doc's exact spacing and the typo `(###, and ###)` — that
  is how it appears in the source.
- For *short* outputs use a softer instruction; this snippet is calibrated for
  long-form content where bullet fragmentation hurts readability.
