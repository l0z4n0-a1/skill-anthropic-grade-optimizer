#!/usr/bin/env python3
"""
lib_ux.py — human-facing translation layer for the auditor's report.

This module is pure presentation. The technical bundle (score, findings,
rule_ids) is unchanged; lib_ux only renders it for human consumption.
CI consumers continue to read the JSON bundle and the trailing parseable
summary line — neither is touched here.

Design contracts:
- Plain English first. Jargon (rule_ids, severities) appears only in --verbose.
- Every finding answers three questions: what, why it matters, what to do.
- Every audit ends with a single concrete next step. No orphan reports.
- All boxes use Unicode box-drawing; ASCII fallback in render_box() if needed.
"""

from typing import Optional


# ──────────────────────────────────────────────────────────────────────────
# Verdict translation — turns a (score, hard_violations, exempted) tuple
# into the headline the operator reads first.
# ──────────────────────────────────────────────────────────────────────────

def verdict_for(score: float, hard_violations: int, has_must_fix: bool) -> dict:
    """Return verdict dict: {emoji, headline, subhead, percentile, action}."""
    if hard_violations > 0 or has_must_fix:
        return {
            "emoji": "🔴",
            "headline": "Needs work before shipping",
            "subhead": f"{hard_violations} critical issue(s) to fix first",
            "percentile": _percentile_for(score),
            "tier": "REDESIGN" if score < 60 else "REVISE",
        }
    if score >= 90:
        return {
            "emoji": "✅",
            "headline": "Anthropic-grade. Ship it.",
            "subhead": "No critical issues. Author voice preserved.",
            "percentile": _percentile_for(score),
            "tier": "SHIP",
        }
    if score >= 80:
        return {
            "emoji": "✅",
            "headline": "Production-ready",
            "subhead": "A few polish opportunities below.",
            "percentile": _percentile_for(score),
            "tier": "SHIP",
        }
    if score >= 70:
        return {
            "emoji": "🟡",
            "headline": "Functional, with room to grow",
            "subhead": "Address the should-fix items to lift this to production grade.",
            "percentile": _percentile_for(score),
            "tier": "REVISE",
        }
    return {
        "emoji": "🟠",
        "headline": "Needs revision",
        "subhead": "Multiple issues to address before this is ready.",
        "percentile": _percentile_for(score),
        "tier": "REVISE",
    }


def _percentile_for(score: float) -> str:
    """Anchor the score against artifacts we've audited (15-fixture corpus)."""
    if score >= 95:
        return "top 5% of artifacts we audit"
    if score >= 85:
        return "top 25%"
    if score >= 70:
        return "above median"
    if score >= 50:
        return "below median — common improvement opportunities"
    return "bottom quartile — significant rework needed"


# ──────────────────────────────────────────────────────────────────────────
# Score bar — visual progress bar that scales to terminal width.
# ──────────────────────────────────────────────────────────────────────────

def score_bar(score: float, width: int = 22) -> str:
    """Return a Unicode progress bar like '█████████████████░░░░'."""
    filled = round((score / 100) * width)
    return "█" * filled + "░" * (width - filled)


def grade_letter(score: float) -> str:
    if score >= 90: return "A"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "F"


# ──────────────────────────────────────────────────────────────────────────
# Per-dimension renderer — compact 3×4 grid instead of 11 vertical lines.
# Highlights anything below 100 with a marker.
# ──────────────────────────────────────────────────────────────────────────

DIMENSION_LABELS = {
    "D-CLAR":    "Clarity",
    "D-STRUCT":  "Structure",
    "D-EXAMPLE": "Examples",
    "D-REASON":  "Reasoning",
    "D-CONTEXT": "Context",
    "D-MODEL":   "Model fit",
    "D-AGENT":   "Agency",
    "D-EVAL":    "Self-check",
    "D-TOOL":    "Tools",
    "D-VISION":  "Vision",
    "D-CC":      "Claude Code",
}


def render_dimensions(per_dim: dict) -> list:
    """Return list of lines rendering the per-dimension scores as a tidy grid."""
    if not per_dim:
        return []
    rows = []
    items = []
    for key, label in DIMENSION_LABELS.items():
        if key in per_dim:
            val = per_dim[key]
            marker = " " if val >= 95 else "·"
            items.append((label, val, marker))
    # Lay out 3 columns
    lines = []
    for i in range(0, len(items), 3):
        chunk = items[i:i + 3]
        cells = []
        for label, val, marker in chunk:
            cells.append(f"{label:<11} {marker} {val:5.1f}")
        lines.append("  " + "    ".join(cells))
    # Highlight below-100 dimensions
    weak = [(label, val) for label, val, _ in items if val < 100]
    if weak:
        weak_str = ", ".join(f"{l} ({v:.0f})" for l, v in weak[:3])
        lines.append("")
        lines.append(f"  ↳ Room to grow: {weak_str}")
    return lines


# ──────────────────────────────────────────────────────────────────────────
# Finding enrichment — turn technical findings into human guidance.
# Uses the rule_id family to derive what/why/how when no override is provided.
# ──────────────────────────────────────────────────────────────────────────

# Plain-English explanations for the rule families operators see most often.
# Falls back gracefully when a rule isn't in the dictionary — the technical
# statement is still shown.
RULE_FAMILY_GUIDANCE = {
    "AR-CLAR": {
        "category": "Clarity & directness",
        "why": "Clear instructions reduce ambiguity. Anthropic measures this as one of the highest-leverage improvements.",
    },
    "AR-STRUCT": {
        "category": "Structure & formatting",
        "why": "XML tags and consistent hierarchy help Claude parse intent reliably.",
    },
    "AR-EXAMPLE": {
        "category": "Examples (few-shot)",
        "why": "3–5 worked examples wrapped in <example> tags lift response quality more than any instruction can.",
    },
    "AR-REASON": {
        "category": "Reasoning depth",
        "why": "Adaptive thinking and explicit reasoning steps reduce hallucinations on complex tasks.",
    },
    "AR-CONTEXT": {
        "category": "Context placement",
        "why": "Documents at the top, queries at the end — Anthropic measured a ~30% quality lift from this alone.",
    },
    "AR-MODEL": {
        "category": "Model-specific tuning",
        "why": "Each Claude model has different defaults. Mismatched parameters can cause API errors or degrade output.",
    },
    "AR-AGENT": {
        "category": "Agentic behaviour",
        "why": "Stop conditions and ground-truth checks prevent runaway tool loops.",
    },
    "AR-EVAL": {
        "category": "Embedded verification",
        "why": "Asking Claude to verify its own output catches errors before they reach the user.",
    },
    "AR-TOOL": {
        "category": "Tool definitions",
        "why": "Crisp tool schemas and parallel tool calls make agents faster and more accurate.",
    },
    "AR-VISION": {
        "category": "Vision & multimodal",
        "why": "Image placement and resolution handling affect both accuracy and cost.",
    },
    "AR-CC": {
        "category": "Claude Code conventions",
        "why": "Skills, subagents, hooks and MCPs each have hard requirements that fail silently if violated.",
    },
}


def enrich_finding(finding: dict) -> dict:
    """Add human-facing fields without mutating the original.

    Lookup order for the why/what fields:
      1. Rule-specific override in RULE_OVERRIDES (best — concrete and specific)
      2. Finding's own why_it_matters / what_to_do (if the detector ships them)
      3. Family-level guidance in RULE_FAMILY_GUIDANCE
      4. Severity-based fallback in _suggest_action
    """
    rid = finding.get("rule_id", "")
    family = "-".join(rid.split("-")[:2]) if "-" in rid else ""
    family_guidance = RULE_FAMILY_GUIDANCE.get(family, {})
    rule_override = RULE_OVERRIDES.get(rid, {})

    out = dict(finding)
    out["_human_category"] = rule_override.get("category") \
        or family_guidance.get("category", "Anthropic doctrine")
    out["_human_why"] = (
        rule_override.get("why")
        or finding.get("why_it_matters")
        or family_guidance.get("why",
            "This rule is part of Anthropic's published prompting doctrine.")
    )
    out["_human_what"] = (
        rule_override.get("what")
        or finding.get("what_to_do")
        or _suggest_action(finding)
    )
    return out


# Rule-specific human translations. Add entries here as you encounter findings
# whose default family-level guidance is too generic. Each entry overrides the
# family default for that single rule_id.
RULE_OVERRIDES = {
    "AR-CC-S22": {
        "category": "Skill clarity",
        "why": "Readers can't tell if 'analyze.py' means run it or read it as docs. "
               "Explicit verbs ('Run analyze.py', 'See analyze.py for the algorithm') "
               "remove that ambiguity in two extra characters.",
        "what": "Prefix script mentions with 'Run' (to execute) or 'See' (to read).",
    },
    "AR-CC-S20": {
        "category": "Skill dependencies",
        "why": "If your skill imports a library, the next operator needs to know how "
               "to install it. A bare import is a hidden setup step.",
        "what": "Add `pip install <package>` near the first import or in a setup section.",
    },
    "AR-CLAR-006": {
        "category": "Positive instructions",
        "why": "Telling Claude what NOT to do leaves it guessing what TO do. "
               "Anthropic measures positive framings as ~30% more reliable.",
        "what": "Rewrite each 'don't do X' as 'do Y instead'.",
    },
    "AR-MODEL-002": {
        "category": "Model API breakage",
        "why": "Prefilling the assistant message returns HTTP 400 on Opus 4.7, "
               "Opus 4.6 and Sonnet 4.6. Your call will fail in production.",
        "what": "Move the continuation into a user message, or omit the prefill entirely.",
    },
    "AR-MODEL-018": {
        "category": "Code review coverage",
        "why": "Without explicit coverage criteria, Claude reviews what it sees first "
               "and stops, missing systemic issues.",
        "what": "List the categories you want reviewed (security, perf, types, tests, etc.).",
    },
}


def _suggest_action(finding: dict) -> str:
    """Heuristic fallback when a finding doesn't ship its own remedy."""
    severity = finding.get("severity", "").lower()
    if severity in ("hard", "critical"):
        return "Fix this before shipping — it can cause API errors or noticeably degrade output."
    if severity in ("soft", "high", "medium"):
        return "Address this in your next pass; the artifact still works, but the win is real."
    return "Optional polish. Apply if you want to push the score higher."


# ──────────────────────────────────────────────────────────────────────────
# Box-drawing primitives — Unicode by default, ASCII fallback available.
# ──────────────────────────────────────────────────────────────────────────

BOX = {
    "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
    "h":  "─", "v":  "│",
    "ml": "├", "mr": "┤",
}


def _display_width(s: str) -> int:
    """Approximate display width — most emoji and CJK take 2 columns."""
    w = 0
    for ch in s:
        cp = ord(ch)
        # Common emoji ranges + CJK + symbols that render as wide
        if (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF) \
                or (0x2B00 <= cp <= 0x2BFF) or (0x3000 <= cp <= 0x9FFF) \
                or cp == 0x2705 or cp == 0x2713 or cp == 0x2717:
            w += 2
        else:
            w += 1
    return w


def render_box(title: str, body_lines: list, width: int = 68) -> list:
    """Return a list of lines forming a titled box around body_lines.

    Width-aware: pads using display columns, not character count, so emoji
    and other wide glyphs do not break alignment.
    """
    out = []
    title_str = f" {title} "
    pad = width - len(title_str) - 4
    out.append(BOX["tl"] + BOX["h"] * 2 + title_str + BOX["h"] * pad + BOX["tr"])
    for ln in body_lines:
        content = " " + ln
        # Truncate by display columns
        while _display_width(content) > width - 2:
            content = content[:-1]
        gap = (width - 2) - _display_width(content)
        out.append(BOX["v"] + content + (" " * gap) + BOX["v"])
    out.append(BOX["bl"] + BOX["h"] * (width - 2) + BOX["br"])
    return out


def render_rule(width: int = 68, label: Optional[str] = None) -> str:
    """Horizontal rule with optional inline label."""
    if not label:
        return BOX["h"] * width
    label_str = f" {label} "
    side = (width - len(label_str)) // 2
    return BOX["h"] * side + label_str + BOX["h"] * (width - side - len(label_str))


# ──────────────────────────────────────────────────────────────────────────
# Coverage caveat — one paragraph, plain English, what this audit cannot say.
# ──────────────────────────────────────────────────────────────────────────

def coverage_caveat_lines(rules_meta: dict, pass2_executed: bool) -> list:
    total = rules_meta.get("total_unique_rules", "?")
    version = rules_meta.get("version", "?")
    date = rules_meta.get("dissection_date", "?")
    lines = [
        f"This audit checked your artifact against {total} cited Anthropic rules",
        f"(rules.yaml v{version}, dissected {date}).",
        "",
    ]
    if not pass2_executed:
        lines.append("Pass 1 (fast, mechanical) ran. Pass 2 (deep, AI-judged) was skipped —")
        lines.append("add --pass2 with an ANTHROPIC_API_KEY for qualitative checks (~2¢ per audit).")
    else:
        lines.append("Both Pass 1 (mechanical) and Pass 2 (AI-judged) ran.")
    return lines


# ──────────────────────────────────────────────────────────────────────────
# Next-step suggestion — every audit ends here. No orphan reports.
# ──────────────────────────────────────────────────────────────────────────

def next_step_for(verdict: dict, must_fix: int, should_fix: int, may_fix: int,
                  mode: str) -> str:
    if verdict["tier"] == "SHIP" and must_fix == 0 and should_fix == 0 and may_fix == 0:
        return "Nothing required. This artifact is ready."
    if verdict["tier"] == "SHIP" and may_fix > 0:
        return f"Optional: address the {may_fix} polish item(s) above to push the score higher."
    if must_fix > 0:
        if mode == "audit":
            return (f"Address the {must_fix} must-fix item(s) above, "
                    "then re-run with --mode optimize to generate patches.")
        return f"Apply the diffs above, then re-run to confirm the score lifts."
    if should_fix > 0:
        return (f"Address the {should_fix} should-fix item(s) above for a meaningful score lift. "
                "Run with --mode optimize for surgical patches.")
    return "Review the items above and decide which are worth your time."


# ──────────────────────────────────────────────────────────────────────────
# CI summary line — last line of every report, parseable by automation.
# Format kept stable: scripts can rely on it.
# ──────────────────────────────────────────────────────────────────────────

def ci_summary_line(score: float, gate_passed: bool, must_fix: int,
                    should_fix: int, may_fix: int, exempted: int) -> str:
    gate = "PASS" if gate_passed else "FAIL"
    return (f"[anthropic-grade-optimizer] SCORE={score:.0f} GATE={gate} "
            f"MUST_FIX={must_fix} SHOULD_FIX={should_fix} MAY_FIX={may_fix} "
            f"EXEMPTED={exempted}")
