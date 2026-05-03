# Snippet: frontend-aesthetics

| field | value |
|---|---|
| triggers_rule | AR-MODEL-006, AR-MODEL-016, AR-MODEL-017 |
| applies_to | system_prompt, skill (frontend domain) |
| model_specific | opus-4-7 |
| verbatim | yes (4.7-calibrated lighter version) |
| source_url | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#design-and-frontend-defaults |
| insertion_pattern | replace any heavier 4.6-era anti-AI-slop scaffolding |
| voice_drift | low |

## When to insert

When AR-MODEL-017 fires (lighter frontend scaffolding sufficient for 4.7) or
AR-MODEL-006 (generic AI aesthetic risk).

## Verbatim block

```text
<frontend_aesthetics>
NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white or dark backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character. Use unique fonts, cohesive colors and themes, and animations for effects and micro-interactions.
</frontend_aesthetics>
```

## Operator notes

- This is the **4.7-calibrated lighter version**. The full 4.6-era version with
  Typography/Color/Motion/Backgrounds breakdown is at the same doc URL but is
  no longer required for 4.7 (per AR-MODEL-017).
- Pair with concrete palette spec (per AR-MODEL-016) — generic negation alone
  bounces 4.7 to a different fixed palette rather than producing variety.
