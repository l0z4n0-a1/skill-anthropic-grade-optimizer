# Doctrinal Gaps — Honest Coverage Statement

Every audit report MUST include a `coverage_caveat` block referencing this file. Anthropic-grade means cited or silent — and silent means *declared*, not hidden.

Dissection date: **2026-05-02**. Re-dissect quarterly or on major model release (H10).

## Major Gaps (10)

### G1 — Quantitative thresholds for "concise"
Doctrine says "be concise" repeatedly. Only `SKILL.md body ≤500 lines` is numeric. No published threshold for prompts, system messages, agent definitions.
**Impact:** Cannot deterministically flag "too long" non-skill artifacts. Use heuristics relative to type-norms.

### G2 — Audit/diagnostic rubric absent
Anthropic doctrine is purely prescriptive ("how to write good prompts"), not diagnostic ("how to score an existing prompt"). No official scoring rubric, no severity weights, no Anthropic-blessed linter.
**Impact:** This skill's rubric is *our* synthesis. Severity classification is inferred from lexical markers (must/never/required = hard; recommended/consider/often = soft). The 11-dimension breakdown is *not* Anthropic-canonical — it is auditor-canonical.

### G3 — Conflict-resolution between rules (RESOLVED in v1.2)

Several rules tension without official Anthropic tie-breaking. v1.2 ships with
explicit auditor tie-breakers. When a conflict fires, the report cites both
rules and applies the tie-breaker below; operators may override via
`--no-conflict-resolution` (audit-only flag for transparency).

| # | Rule A | Rule B | Tie-breaker (applies when both fire) | Rationale |
|---|---|---|---|---|
| C1 | "Be detailed" (AR-CLAR-001) | "Concise responses" (AR-MODEL-010) | **Detail wins for prompts; concision wins for output instructions.** | Detail belongs on the *input* side (the prompt's clarity); concision belongs on the *output* side (Claude's response). Both rules are correct in scope. |
| C2 | "3-5 examples" (AR-EXAMPLE-004) | "≤500 lines SKILL.md" (AR-SKILL-004) | **Examples win.** Move overflow to `assets/snippets/` and reference from SKILL.md. | Anthropic's own skill-creator pattern uses asset references when body grows. The 500-line cap is about cognitive load, not example count. |
| C3 | "Tell what to DO" (AR-CLAR-006) | Anti-pattern lists (negative form) | **Negative form is allowed when paired with a positive alternative in the same paragraph.** Bare prohibitions still trigger AR-CLAR-006. | The doctrine's intent is "don't leave Claude guessing what to do instead." Pairing satisfies that intent. |
| C4 | "Use XML" (AR-STRUCT-001) | "Match prompt style to output style" (AR-CLAR-007) | **XML wins for scaffolding; prose-matching wins for content blocks.** | XML is a structural affordance the model recognizes regardless of output format. Style-matching applies to the *content* the model produces inside the structure. |
| C5 | Best-practices emphasis endorsement | skill-creator yellow-flag on ALL-CAPS | **Resolved as D9 type-aware (already implemented):** ENDORSED for `claude_md`/`system_prompt`/`user_prompt`; YELLOW for `skill`/`subagent` body. | Best-practices addresses Claude.com prompts; skill-creator addresses skill bodies which the model reads as instructions about authoring, not as the prompt itself. |

Wiring: see `references/rubric-by-type.yaml § conflict_resolution`. Each
fired conflict appears in the report as a single `[CONFLICT-Cn]` entry with
both rule_ids cited, the tie-breaker applied, and the rationale visible.

### G4 — No guidance for non-API artifact types
Anthropic explicitly addresses: `system_prompt`, `user_prompt`, `SKILL.md`, frontend skill, tool definitions. Does NOT directly address:
- `CLAUDE.md` (now covered via memory.md, but late addition)
- Slash commands legacy spec
- Subagent body authoring (only frontmatter spec)
- Workflows / pipeline chains beyond "self-correction"
- MCP server authoring style

**Impact:** Some auditing relies on extrapolation from system_prompt rules. Mark as `applicability: extrapolated` in those cases.

### G5 — Severity (hard/soft) not natively labeled
Anthropic does not formally tag rules. Severity inferred lexically.
**Impact:** Some "hard"-classified rules may relax in future doctrine versions.

### G6 — Versioning & deprecation cadence
No published versioning of the prompt-engineering doctrine itself. Rules change silently between model generations (prefill deprecation 4.6+, "think" word sensitivity on 4.5).
**Impact:** Quarterly re-dissection mandatory. `dissected_at` field on every audit.

### G7 — Token-budget impacts of obeying rules
Rules cost tokens. "Wrap variables in XML" + "3-5 examples" + "long context grounding via quotes" all add tokens.
**Impact:** Skill cannot offer cost-benefit per rule. Operator decides.

### G8 — Cultural / multilingual / accessibility
Anglocentric doctrine. No guidance on non-English, RTL, accessibility-first, culturally-specific norms.
**Impact:** Skill should NOT impose English-centric style on non-English artifacts. Auto-detect language; suppress style rules that don't translate.

### G9 — Identity / persona engineering depth
"Give Claude a role" treated as single-sentence affordance. NO doctrine for: persona consistency across long sessions, multi-agent identity differentiation, identity-precedes-behavior philosophy, archetypal framing.
**Impact:** Identity-first prompt design extends beyond Anthropic's published doctrine. Treat external persona-engineering frameworks as compatible extensions, never as compliance tests under `AR-*` rule_ids.

### G10 — Empirical evidence base
Most rules are expert recommendation, not eval-backed. Notable exceptions: "30% quality lift from end-of-prompt queries" (AR-CONTEXT-002), "54% improvement from think-tool" (think-tool blog post).
**Impact:** Anthropic recommends users run their own evals (AR-SKILL-011). This skill recommends the same.

## Minor Gaps (10+)

- Few-shot count calibration per model (only "3-5" universal)
- Verbosity baselines (no absolute numbers)
- XML-vs-Markdown per-model preference (universal)
- Hallucination benchmarks comparative
- Sonnet 4.6 long-context premium status (medium confidence: assumed no premium)
- Adaptive-thinking interaction with system-prompt size
- Haiku 4.5 prefill removal status (4.5 named; doc says "starting 4.6" — ambiguous)
- Opus 4.7 context-awareness (NOT listed alongside Sonnet 4.6 / Haiku 4.5 — possible omission)
- `task_budget` per-model availability (Opus 4.7 only?)
- MCP server authoring best practices (modelcontextprotocol.io has spec; Anthropic-Claude-Code-specific style guide absent)
- Hook execution order when multiple PostToolUse hooks match (PreToolUse precedence is documented; PostToolUse is not)
- Subagent description char budget (skills have 1536; subagents have no published cap)
- Notebooks in github.com/anthropics/claude-cookbooks — not dissected at template level (deferred to round 3)

## Resolution Path

1. **Empirical testing** for inferred Haiku 4.5 cells → measured deltas
2. **Watch Anthropic releases** — `whats-new` pages add detail post-launch
3. **Cookbook GitHub raw fetches** — deferred to next dissection round
4. **Mark all gap-filled content** with `confidence: low` and `inferred_from`

## Format for `coverage_caveat` block in reports

Every audit report should append:

```
COVERAGE CAVEAT
━━━━━━━━━━━━━━━
Doctrine dissected: 2026-05-02 (<N> days ago)
Rules cited: <count> with verbatim source_url
Known doctrinal gaps: 10 majors, 13+ minors (see references/gaps.md)
Model profile: <target_model> — <high/medium/low/INFERRED> confidence

This audit covers what Anthropic publishes. It cannot cover:
- Internal/unpublished Anthropic guidance
- Empirical thresholds Anthropic does not quantify (G1, G7, G10)
- Conflicts Anthropic has not officially resolved (G3 — see open questions)

Recommend re-running on quarterly cadence or after major model release.
```
