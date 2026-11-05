# Snippet: frontend-aesthetics

| field | value |
|---|---|
| triggers_rule | AR-MODEL-006, AR-MODEL-016, AR-MODEL-017 |
| applies_to | system_prompt, skill (frontend domain) |
| model_specific | opus-4-8, sonnet-5, opus-4-7 |
| verbatim | yes (lighter version calibrated for 4.7+) |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-4-8#design-and-frontend-defaults |
| insertion_pattern | replace any heavier 4.6-era anti-AI-slop scaffolding |
| voice_drift | low |

## When to insert

When AR-MODEL-017 fires (lighter frontend scaffolding sufficient for 4.7+) or
AR-MODEL-006 (generic AI aesthetic risk).

## Verbatim block

```text
<frontend_aesthetics>
NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white or dark backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character. Use unique fonts, cohesive colors and themes, and animations for effects and micro-interactions.
</frontend_aesthetics>
```

## Operator notes

- This is the **lighter version calibrated for Opus 4.8/4.7 and Sonnet 5**
  (published verbatim on both per-model prompting pages). The full 4.6-era
  version with Typography/Color/Motion/Backgrounds breakdown lives on
  claude-prompting-best-practices#frontend-design and is no longer required
  for 4.7+ (per AR-MODEL-017).
- Pair with concrete palette spec (per AR-MODEL-016) — generic negation alone
  bounces the model to a different fixed palette rather than producing variety.
- Sonnet 5 has no temperature — the propose-4-directions pattern is the
  recommended substitute for temperature-driven design variety.
