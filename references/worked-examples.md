# Worked Examples — full walkthroughs

> Moved verbatim from SKILL.md body (poda 2026-07-02). The body keeps ONE golden
> example inline (worked example 1); load this file for the other two or to see
> the golden's negative twin.

## Worked example 1 — auditing a SKILL.md for Opus 4.7

<example>
Operator request: "audit this skill for Opus 4.7"
Artifact: `~/.claude/skills/pdf-tools/SKILL.md` (240 lines)

Step 1 — Classify: type=`skill`, has_frontmatter=true, body_lines=235.
Step 2 — Load rubric: 24 D-SKILL rules + 17 D-CLAR + 10 D-STRUCT + 8 D-EXAMPLE +
         5 D-EVAL + safety. Suppress AR-CC-S09 doctrine-conflict?  No (skill body).
Step 3 — Pass 1 fires: AR-CC-S20 (lib mentioned without `pip install`), AR-CC-S22
         (3 script refs unframed), AR-CLAR-006 (7 negatives, 1 positive alt).
Step 4 — Triage: 1 🔴 (AR-CC-S20), 2 🟢 (S22, CLAR-006).
Step 5 — Optimize emits snippet patches: none (no rule with canonical snippet
         fires). Inline diff for AR-CC-S20 adds "Install required package: pip install pypdf".
Step 6 — Validate: post-diff score 92 (was 78). Voice drift 4% — under 10% gate.
Step 7 — Emit concise report.
</example>

❌ **Negative twin** (nearest-plausible wrong execution): Step 5 emits a full
rewrite of the skill's installation section as prose ("You should install pypdf
before using this skill because...") instead of the single-line inline diff. Why
this is wrong: the Three Laws require voice-preserving surgical diffs — a rewrite
that adds explanatory prose not requested by the operator increases voice_drift
past the 10% gate and would abort in Step 6, not pass at 92.

## Worked example 2 — strange-loop self-audit

<example>
Operator request: "run the skill on its own SKILL.md"
Artifact: `anthropic-grade-optimizer/SKILL.md`

Step 3 — Pass 1 fires: AR-CC-S14 (name contains "anthropic" reserved word) and
         possibly AR-CC-S21 (TOC) and AR-CC-S22 (script framing).
Step 4 — AR-CC-S14: see § Self-audit: Open Questions in SKILL.md for the operator's
         documented decision (semantic-justification exception).
Step 5 — No-op for the AR-CC-S14 finding (declared exception).
Step 7 — Concise report flags the open question and links to the §.
</example>

## Worked example 3 — auditing an api_config snippet

<example>
Operator request: "is this Python snippet safe for Opus 4.7?"
Artifact: a `client.messages.create(...)` call with `temperature=0.7`,
          `effort='low'`, last message role=assistant.
Type: `api_config`. Target: `claude-opus-4-7`.

Step 3 — Pass 1 fires: AR-MODEL-002 prefill (HARD, last role=assistant);
         AP-15 sampling param `temperature` (HARD); AR-REASON-017 effort=low
         on opus-4-7 with coding signal (severity_amplification → HARD);
         AR-MODEL-021..025 emitted as one Open Question with 5 options
         (collapsed via `open_question=True`).
Step 4 — Triage: 3 🔴 (002, AP-15, REASON-017), 1 ❓ (021..025).
Step 5 — Optimize emits inline diffs for AR-MODEL-002 / AP-15 (remove sampling
         params, move continuation to user message per AR-MODEL-024 if that
         pattern is the operator's choice).
</example>
