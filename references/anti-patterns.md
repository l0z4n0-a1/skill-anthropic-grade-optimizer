# Anti-Patterns (AP-1 to AP-15)

Detection-ready catalog of what to flag and what NOT to flag.

## AP-1 — Anthropic Cargo Cult
**Pattern:** Applying an Anthropic rule literally without contextual understanding.
**Detection:** Manual review during P3 (DIAGNOSE).
**Prevention:** Every finding cites both the rule AND the contextual reason it applies here.

## AP-2 — Score-Maximization
**Pattern:** Optimizing for the number, not the result.
**Detection:** `voice_drift_score > 10%` while score rises.
**Prevention:** Voice-drift gate; modo AFFIRMATION when initial score ≥85.

## AP-3 — Non-Anthropic Source Disguised as Anthropic
**Pattern:** Presenting an external technique or heuristic as if it were Anthropic doctrine.
**Detection:** Finding has `rule_id` but no `source_url`, or `source_url` points outside the official Anthropic source list (`platform.claude.com`, `code.claude.com`, `anthropic.com/engineering`, `github.com/anthropics`).
**Prevention:** Emitter rejects findings without `source_url`. Non-Anthropic enrichments must carry the `EXTERNAL_ENRICHMENT` tag and never be reported under an `AR-*` rule_id.

## AP-4 — Masked Rewrite
**Pattern:** "Diff" that effectively rewrites the artifact.
**Detection:** `diff_modified_chars / artifact_chars > 40%`.
**Prevention:** Flag and require operator confirmation. H2 (Surgical over Sweeping).

## AP-5 — Audit Theater
**Pattern:** Beautiful reports with no actionable diff.
**Detection:** mode `audit` produced 10+ 🔴 findings but operator never advances to `optimize`.
**Prevention:** K1 (Score Lift) tracked. Default `audit` mode acceptable, but expose `--mode=full` clearly.

## AP-6 — Forgotten Model
**Pattern:** Applying a rule that holds for Opus to an artifact targeting Haiku.
**Detection:** Finding does not check `applicability.model_specific` against `target_model`.
**Prevention:** D-MODEL is mandatory dimension; H5 (Model-First Lens).

## AP-7 — Stalled Dissection
**Pattern:** Running with a 6-month-old snapshot of Anthropic docs.
**Detection:** `dissected_at > 90 days` on any cited rule.
**Prevention:** H10 (Freshness Audit) auto-warning.

## AP-8 — Genericized Voice
**Pattern:** After N optimizations, all of operator's artifacts sound the same.
**Detection:** Track voice fingerprint across artifacts; alert on convergence.
**Prevention:** Optional `voice-fingerprint.yaml` declaring protected markers as hard-PRESERVE.

## AP-9 — Forgotten Type ⚡ (Round 2)
**Pattern:** Applying a SKILL.md rule to a CLAUDE.md, or a subagent rule to a hook config.
**Detection:** Audit run did not load `rubric-by-type.yaml` for the detected type.
**Prevention:** H11 (Artifact-Type-First) is mandatory before any audit. K7 (Type-Match Rate).
**Example:** Firing AR-SKILL-001 (frontmatter constraint) on a CLAUDE.md (which has no SKILL frontmatter) = AP-9.

## AP-10 — Blind Emphasis-Conflict ⚡ (Round 2)
**Pattern:** Flagging `IMPORTANT` / `YOU MUST` in CLAUDE.md as a violation.
**Detection:** Finding fires AR2-SKILL-BLG-003 on artifact_type ∈ {claude_md, system_prompt, user_prompt}.
**Prevention:** D9 resolution. `false_positive_rules` in `rubric-by-type.yaml` suppresses AR2-SKILL-BLG-003 on these types.
**Reason:** best-practices.md explicitly endorses emphasis on instruction-style artifacts. Yellow-flag only applies to skill/subagent body.

## AP-11 — Silent Custom Frontmatter ⚡ (Round 2)
**Pattern:** Skill or subagent file with frontmatter keys outside the canonical set (e.g., `phase`, `gate`, `P0-P5`, `layer`, `cognitive-architecture`).
**Detection:** Parse frontmatter; set-difference against canonical key list (see `rubric-by-type.yaml`).
**Prevention:** Detect and warn 🟡. Custom keys are silently ignored by Claude Code → invisible drift.

## AP-12 — Recursive Subagent Spawn ⚡ (Round 2)
**Pattern:** Subagent body that tries to invoke another subagent (Task tool, @-mention of agent name).
**Detection:** Regex on subagent body for `Task(`, `@agent-`, or "use the X subagent".
**Prevention:** Hard rule AR2-CC-043. Always 🔴.

## AP-13 — Hook Exit-Code-1 Expecting Block ⚡ (Round 2)
**Pattern:** Hook script uses `exit 1` expecting Claude Code to abort the action.
**Detection:** Read referenced hook script; grep for `exit 1` in PreToolUse / PermissionRequest / UserPromptSubmit / Stop / TaskCompleted handlers.
**Prevention:** AR2-CC-062. Only `exit 2` blocks for these events. `exit 1` is non-blocking. Always 🔴.

## AP-14 — Prefill on Modern Model ⚡ (Round 2)
**Pattern:** API artifact targets Claude Opus 4.7 / Opus 4.6 / Sonnet 4.6 with `prefill` set on assistant message.
**Detection:** Inspect API call structure; if last message has `role: assistant` with content (prefill pattern) and target model in {opus-4-7, opus-4-6, sonnet-4-6} → 🔴.
**Prevention:** AR2-CC-002 / AR-MODEL-002. Returns 400 error in production.

## AP-15 — Sampling Params on Opus 4.7 ⚡ (Round 2)
**Pattern:** API artifact targets Opus 4.7 with `temperature`, `top_p`, or `top_k` set to non-default values.
**Detection:** Inspect API config; if target = opus-4-7 and any of these params present → 🔴.
**Prevention:** AR2-MODEL-* (migration guide). Returns 400 error.

---

## Detection Quick-Reference

| Anti-pattern | Detection method | Severity |
|---|---|---|
| AP-1 Cargo Cult | manual P3 review | n/a (process) |
| AP-2 Score-Max | voice_drift gate | abort optimization |
| AP-3 Non-Anthropic Disguised | source_url required check | reject finding |
| AP-4 Masked Rewrite | diff char ratio > 40% | require confirmation |
| AP-5 Audit Theater | K1 tracked | n/a (skill UX) |
| AP-6 Forgotten Model | check model_specific | re-classify finding |
| AP-7 Stalled | dissected_at age | warning banner |
| AP-8 Voice Generic | fingerprint tracking | preserve override |
| **AP-9 Forgotten Type** | rule.applicability vs artifact.type | suppress finding |
| **AP-10 Emphasis Blind** | false_positive_rules suppression | suppress finding |
| **AP-11 Custom Frontmatter** | frontmatter set-diff | 🟡 SHOULD-FIX |
| **AP-12 Recursive Spawn** | regex on subagent body | 🔴 MUST-FIX |
| **AP-13 Hook Exit 1** | grep on hook scripts | 🔴 MUST-FIX |
| **AP-14 Prefill Modern** | API call inspection | 🔴 MUST-FIX |
| **AP-15 Sampling Opus 4.7** | API params check | 🔴 MUST-FIX |
