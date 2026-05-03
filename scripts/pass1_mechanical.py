#!/usr/bin/env python3
"""
pass1_mechanical.py — v1.2 (E2 Determinism Patch)

USO: python pass1_mechanical.py <path> --type <artifact_type> [--target-model M]
QUANDO USAR: P2 (AUDIT) Pass 1 — detecções determinísticas via regex/code-check.
OUTPUT: JSON com findings (rule_id, severity, triage, evidence, location).

Coverage v1.2 (post E2):
  - Mechanical detectors: ~50 rules covered in Pass 1 (was ~32 in v1.0)
  - New artifact type: api_config (audit_api_config)
  - v1.2 currency-patch detectors:
      AR-CC-S13/S14/S15/S19/S20/S21/S22 in audit_skill
      AR-MODEL-014/015/016/018, AR-REASON-019 in audit_prompt
      AR-MODEL-002/003/004/021..025, AR-REASON-017/018, AR-VISION-001 in audit_api_config
      AP-15 sampling-params on Opus 4.7 in audit_api_config
  - Reclassifications: AR-STRUCT-006, AR-EXAMPLE-005/008, AR-REASON-007,
                       AR-CONTEXT-003, AR-AGENT-009 promoted from heuristic to regex
  - Hybrid support: make_finding(**extra) accepts requires_pass2_grade,
                    domain_signal, group, etc.

Pass 2 (llm-judge) covers the remaining ~139 qualitative rules via
references/pass2-protocol.md.

SSOT for rule definitions: references/rules-anthropic.yaml § meta.total_unique_rules
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows (per AR-CC-S06 — cross-platform script behavior)
# Without this, Unicode triage glyphs (🔴/🟡/🟢) crash on cp1252 terminals.
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def find_lines(content: str, pattern: str, flags: int = 0) -> list:
    out = []
    for i, line in enumerate(content.splitlines(), start=1):
        if re.search(pattern, line, flags):
            out.append((i, line.strip()))
    return out


def make_finding(finding_id, rule_id, dimension, severity, triage, statement,
                 source_url, verbatim_quote, evidence, location, detection_method,
                 score_impact, **extra):
    """Build a finding record. Extra kwargs (e.g., requires_pass2_grade,
    domain_signal, applicability) are passed through verbatim to support
    hybrid detection rules and v1.2 currency-patch metadata."""
    finding = {
        "finding_id": finding_id,
        "rule_id": rule_id,
        "dimension": dimension,
        "severity": severity,
        "triage": triage,
        "statement": statement,
        "source_url": source_url,
        "verbatim_quote": verbatim_quote,
        "evidence": evidence,
        "location": location,
        "detection_method": detection_method,
        "score_impact": score_impact,
    }
    finding.update(extra)
    return finding


# ═══════════════════════════════════════════════════════════════
# CLAUDE.md audits
# ═══════════════════════════════════════════════════════════════

def audit_claude_md(path: Path, content: str, fm: dict) -> list:
    findings = []
    lines = content.splitlines()
    line_count = len(lines)

    # AR-CC-002: <=200 lines target
    if line_count > 200:
        impact = -15 if line_count > 400 else -10 if line_count > 300 else -7
        findings.append(make_finding(
            "F-CC-002", "AR-CC-002", "D-CC", "high", "🟡",
            "CLAUDE.md must target under 200 lines",
            "https://code.claude.com/docs/en/memory#write-effective-instructions",
            "Size: target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence.",
            f"file has {line_count} lines (target: 200)",
            "whole-file", "code-check", impact))

    # AR-CLAR-006: positive over negative
    negative_count = len(re.findall(r"\b(do not|don't|never|no\b)\b", content, re.IGNORECASE))
    positive_alt_count = len(re.findall(r"\binstead\b|\brather\b|\binstead of\b", content, re.IGNORECASE))
    if negative_count > 5 and positive_alt_count < negative_count // 2:
        findings.append(make_finding(
            "F-CLAR-006", "AR-CLAR-006", "D-CLAR", "hard", "🔴",
            "Tell what to DO instead of what NOT to do",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#control-the-format-of-responses",
            "Tell Claude what to do instead of what not to do.",
            f"{negative_count} negative imperatives, only {positive_alt_count} positive alternatives",
            "scattered", "regex", -12))

    # AR-CC-003: facts not procedures (heuristic — multi-step numbered lists)
    numbered_list_count = len(re.findall(r"^\d+\.\s+\w+", content, re.MULTILINE))
    if numbered_list_count > 8:
        findings.append(make_finding(
            "F-CC-003", "AR-CC-003", "D-CC", "high", "🟡",
            "Multi-step procedures should be Skills, not memory",
            "https://code.claude.com/docs/en/memory#when-to-add-to-claude-md",
            "If an entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped rule instead.",
            f"{numbered_list_count} numbered list items detected — looks procedural",
            "scattered", "heuristic", -8))

    # AR-CC-004: vague verbs without concrete spec
    vague_verbs = re.findall(r"\b(properly|nicely|cleanly|good|properly|things|stuff|appropriate)\b",
                              content, re.IGNORECASE)
    if len(vague_verbs) > 3:
        findings.append(make_finding(
            "F-CC-004", "AR-CC-004", "D-CC", "high", "🟡",
            "Instructions must be specific and verifiable, not abstract",
            "https://code.claude.com/docs/en/memory#write-effective-instructions",
            "Specificity: write instructions that are concrete enough to verify.",
            f"vague terms detected: {list(set(vague_verbs))[:5]}",
            "scattered", "regex", -7))

    # AR-CC-005: @import depth (heuristic — count @imports)
    import_count = len(re.findall(r"^@\S+", content, re.MULTILINE))
    if import_count > 10:
        findings.append(make_finding(
            "F-CC-005", "AR-CC-005", "D-CC", "medium", "🟡",
            "Heavy @import use — verify max 5-hop depth not exceeded",
            "https://code.claude.com/docs/en/memory#import-additional-files",
            "Imported files can recursively import other files, with a maximum depth of five hops.",
            f"{import_count} @imports in single file",
            "scattered", "code-check", -3))

    # AR-CONTEXT-013: bloated CLAUDE.md (repetition detection)
    repeated_lines = {}
    for line in lines:
        line_clean = line.strip()
        if len(line_clean) > 30:
            repeated_lines[line_clean] = repeated_lines.get(line_clean, 0) + 1
    high_repeat = {k: v for k, v in repeated_lines.items() if v > 3}
    if high_repeat:
        findings.append(make_finding(
            "F-CONTEXT-013", "AR-CONTEXT-013", "D-CONTEXT", "hard", "🔴",
            "Bloated CLAUDE.md — repetitive content should be ruthlessly pruned",
            "https://code.claude.com/docs/en/best-practices",
            "Bloated CLAUDE.md files cause Claude to ignore your actual instructions! For each line, ask: 'Would removing this cause Claude to make mistakes?' If not, cut it.",
            f"{len(high_repeat)} lines repeated {max(high_repeat.values())}+ times",
            "scattered", "heuristic", -10))

    return findings


# ═══════════════════════════════════════════════════════════════
# SKILL.md audits
# ═══════════════════════════════════════════════════════════════

def audit_skill(path: Path, content: str, fm: dict) -> list:
    findings = []
    lines = content.splitlines()
    body_start_idx = 0
    if content.lstrip().startswith("---\n"):
        parts = content.split("---\n", 2)
        if len(parts) >= 3:
            body_start_idx = content.index(parts[2])
    body = content[body_start_idx:] if body_start_idx else content
    body_lines = body.count("\n") + 1

    # AR-CC-024: <=500 lines body
    if body_lines > 500:
        impact = -20 if body_lines > 800 else -15 if body_lines > 600 else -10
        findings.append(make_finding(
            "F-CC-024", "AR-CC-024", "D-CC", "hard", "🔴",
            "Keep SKILL.md body under 500 lines",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "Keep SKILL.md body under 500 lines for optimal performance.",
            f"body has {body_lines} lines (cap: 500)",
            "whole-file", "code-check", impact))

    # AR-CC-022: name regex
    name = fm.get("name", "")
    if name and not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        findings.append(make_finding(
            "F-CC-022", "AR-CC-022", "D-CC", "critical", "🔴",
            "Skill name must match ^[a-z0-9-]{1,64}$",
            "https://code.claude.com/docs/en/skills#frontmatter-reference",
            "name: lowercase letters, numbers, and hyphens only (max 64 characters).",
            f"name = '{name}'",
            "frontmatter.name", "regex", -20))

    # AR-CC-S02: third-person description
    description = fm.get("description", "")
    first_person_match = re.search(
        r"\b(I can|I will|I'll|I help|I am|we will|we'll|we help|we are|"
        r"you can use this|you can use me|you can ask me)\b",
        description, re.IGNORECASE)
    if first_person_match:
        findings.append(make_finding(
            "F-CC-S02", "AR-CC-S02", "D-CC", "hard", "🔴",
            "Skill description must be in third person",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "Always write in third person. The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems.",
            f"first/second-person marker: '{first_person_match.group(0)}'",
            "frontmatter.description", "regex", -15))

    # AR-CC-S01: description char limit
    if description and len(description) > 1024:
        findings.append(make_finding(
            "F-CC-S01a", "AR-CC-S01", "D-CC", "hard", "🔴",
            "description field exceeds 1024 character cap",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "description: Must be non-empty, Maximum 1024 characters.",
            f"description is {len(description)} chars (cap: 1024)",
            "frontmatter.description", "code-check", -10))

    # AR-CC-023: description + when_to_use combined cap
    when_to_use = fm.get("when_to_use", "")
    combined = len(description) + len(when_to_use)
    if combined > 1536:
        findings.append(make_finding(
            "F-CC-023", "AR-CC-023", "D-CC", "high", "🟡",
            "description + when_to_use truncated at 1536 chars in skill listing",
            "https://code.claude.com/docs/en/skills#frontmatter-reference",
            "the combined description and when_to_use text is truncated at 1,536 characters in the skill listing to reduce context usage. Put the key use case first.",
            f"combined length = {combined} chars",
            "frontmatter", "code-check", -8))

    # AR-CC-S03: description includes WHEN to use (heuristic — looks for trigger phrases)
    when_indicators = re.search(
        r"\b(use when|use this|trigger|when (?:the )?user|"
        r"asks to|wants to|even if|migrating|reviewing)\b",
        description + " " + when_to_use, re.IGNORECASE)
    if description and not when_indicators:
        findings.append(make_finding(
            "F-CC-S03", "AR-CC-S03", "D-CC", "high", "🟡",
            "Skill description must include WHEN to use it, not just WHAT it does",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview",
            "The description should include both what the Skill does and when Claude should use it.",
            "no trigger phrases (use when/trigger/asks to) in description+when_to_use",
            "frontmatter.description", "heuristic", -8))

    # AR-CC-S06: forward slashes only
    backslash_paths = re.findall(r"[A-Z]:\\\\|[A-Z]:\\|(?<!\\)\\\\(?!\\)", content)
    if backslash_paths:
        findings.append(make_finding(
            "F-CC-S06", "AR-CC-S06", "D-CC", "hard", "🔴",
            "Use forward slashes in file paths, even on Windows",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "Always use forward slashes in file paths, even on Windows.",
            f"backslash path detected (e.g. {backslash_paths[0][:40]})",
            "scattered", "regex", -10))

    # AR-CC-S09: ALL-CAPS yellow flag in body (D9 — applies to skill type)
    actual_imperatives = []
    for caps_word in re.findall(r"\b[A-Z]{4,}\b", body):
        if caps_word in ("ALWAYS", "NEVER", "MUST", "CRITICAL", "REQUIRED",
                         "DO NOT", "EXACTLY", "ONLY"):
            actual_imperatives.append(caps_word)
    if len(actual_imperatives) > 5:
        findings.append(make_finding(
            "F-CC-S09", "AR-CC-S09", "D-CC", "soft", "🟡",
            "ALL-CAPS imperatives are yellow flag in skill body — explain WHY instead",
            "https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md",
            "If you find yourself writing ALWAYS or NEVER in all caps, or using super rigid structures, that's a yellow flag — if possible, reframe and explain the reasoning.",
            f"{len(actual_imperatives)} all-caps imperatives in body: {list(set(actual_imperatives))[:5]}",
            "scattered", "regex", -6))

    # AR-CC-025: side-effecting workflows must disable model invocation
    side_effect_pattern = re.compile(
        r"^name:\s*(deploy|commit|push|publish|release|send|delete|drop|merge|publish)",
        re.MULTILINE)
    if side_effect_pattern.search(content):
        if not re.search(r"disable-model-invocation:\s*true", content):
            findings.append(make_finding(
                "F-CC-025", "AR-CC-025", "D-CC", "high", "🟡",
                "Side-effecting workflow must set disable-model-invocation: true",
                "https://code.claude.com/docs/en/skills#control-who-invokes-a-skill",
                "Use this for workflows with side effects... You don't want Claude deciding to deploy because your code looks ready.",
                f"name suggests side-effect (deploy/commit/push/etc) but disable-model-invocation not set",
                "frontmatter", "heuristic", -8))

    # AR-CC-S10: large reference files should have TOC (heuristic — body section count)
    h2_count = len(re.findall(r"^##\s+", body, re.MULTILINE))
    if body_lines > 300 and h2_count > 8:
        if not re.search(r"##\s*(table of contents|TOC|contents)\b",
                         body[:2000], re.IGNORECASE):
            findings.append(make_finding(
                "F-CC-S10", "AR-CC-S10", "D-CC", "soft", "🟢",
                "Large skill body should include table of contents",
                "https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md",
                "For large reference files (>300 lines), include a table of contents.",
                f"body is {body_lines} lines with {h2_count} sections — no TOC found",
                "skill body", "heuristic", -2))

    # AR-CC-021: custom frontmatter keys (silently ignored)
    canonical_fm = {
        "name", "description", "when_to_use", "argument-hint", "arguments",
        "disable-model-invocation", "user-invocable", "allowed-tools",
        "model", "effort", "context", "agent", "hooks", "paths", "shell",
    }
    custom_keys = set(fm.keys()) - canonical_fm
    if custom_keys:
        findings.append(make_finding(
            "F-CC-021", "AR-CC-021", "D-CC", "high", "🟡",
            "Custom frontmatter keys are silently ignored",
            "https://code.claude.com/docs/en/skills#frontmatter-reference",
            "Allowed frontmatter: name, description, when_to_use, argument-hint, arguments, disable-model-invocation, user-invocable, allowed-tools, model, effort, context, agent, hooks, paths, shell.",
            f"unknown keys: {sorted(custom_keys)}",
            "frontmatter", "code-check", -6))

    # ───── v1.2 currency-patch detectors (E2) ─────

    # AR-CC-S14: reserved words in name (HARD, zero-tolerance)
    if name and re.search(r"\b(anthropic|claude)\b", name, re.IGNORECASE):
        findings.append(make_finding(
            "F-CC-S14", "AR-CC-S14", "D-CC", "hard", "🔴",
            "Skill name must not contain reserved words 'anthropic' or 'claude'",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "Cannot contain reserved words: 'anthropic', 'claude'.",
            f"name = '{name}' contains reserved word",
            "frontmatter.name", "regex", -15))

    # AR-CC-S13: gerund-form name preferred (soft)
    if name:
        is_gerund = name.endswith("-ing") or "-ing-" in name
        is_action_prefix = bool(re.match(r"^(process|analyze|generate|create|review|audit|build|extract|transform|optimize|validate|test|debug)-", name))
        is_noun_phrase = bool(re.match(r"^[a-z]+(?:-[a-z]+)+$", name)) and not is_gerund and not is_action_prefix
        if not (is_gerund or is_action_prefix or is_noun_phrase):
            findings.append(make_finding(
                "F-CC-S13", "AR-CC-S13", "D-CC", "soft", "🟢",
                "Prefer gerund form for skill names (processing-pdfs, analyzing-spreadsheets)",
                "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
                "Consider using gerund form (verb + -ing) for Skill names, as this clearly describes the activity or capability the Skill provides.",
                f"name '{name}' is neither gerund (-ing), action-prefix (verb-X), nor noun-phrase form",
                "frontmatter.name", "regex", -2))

    # AR-CC-S15: time-sensitive language (soft)
    # Strip "old patterns"/"deprecated"/"legacy" sections (canonical-doc-allowed pattern)
    # before searching, so historical context isn't flagged.
    body_for_time = re.sub(
        r"##\s*(old patterns|legacy|deprecated|historical|migration history)[\s\S]*?(?=\n##|\Z)",
        "", body, flags=re.IGNORECASE)
    # Also strip <details> blocks (the doc's recommended pattern for old patterns).
    body_for_time = re.sub(r"<details>[\s\S]*?</details>", "", body_for_time, flags=re.IGNORECASE)
    months = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    time_pattern = re.compile(
        rf"\b(before|after|until|by)\s+(?:{months}\s+)?\d{{4}}\b",
        re.IGNORECASE)
    time_matches = time_pattern.findall(body_for_time)
    if time_matches:
        findings.append(make_finding(
            "F-CC-S15", "AR-CC-S15", "D-CC", "soft", "🟢",
            "Avoid time-sensitive language; use an 'old patterns' section instead",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "Don't include information that will become outdated... Use 'old patterns' section: provides historical context without cluttering the main content.",
            f"time-sensitive phrases in active content (old-patterns/legacy sections excluded): {time_matches[:3]}",
            "scattered", "regex", -2))

    # AR-CC-S22: execution intent explicit (soft)
    # Detect: inline references to .py / scripts in PROSE (not inside code blocks)
    # without "Run"/"See" framing. Code blocks are excluded because script names
    # there are syntax, not instructions to Claude.
    body_no_code = re.sub(r"```[\s\S]*?```", "", body)  # strip fenced code blocks
    body_no_code = re.sub(r"`[^`\n]*`", lambda m: m.group(0) if "." in m.group(0) and re.match(r"`[\w/]+\.(?:py|sh|js|ts|rb)`", m.group(0)) else "", body_no_code)
    script_refs = re.findall(r"`([\w/]+\.(?:py|sh|js|ts|rb))`", body_no_code)
    if script_refs:
        unframed_count = 0
        seen = set()
        for sref in set(script_refs):
            for match in re.finditer(rf"`{re.escape(sref)}`", body_no_code):
                start = max(0, match.start() - 60)
                preceding = body_no_code[start:match.start()].lower()
                has_framing = bool(re.search(
                    r"\b(run|runs|running|execute|invoke|invokes|call|calls|see|read|review|view|via|using)\b",
                    preceding))
                if not has_framing:
                    key = (sref, match.start())
                    if key not in seen:
                        seen.add(key)
                        unframed_count += 1
        if unframed_count >= 3:  # raised threshold from 2 to 3 — fewer false positives
            findings.append(make_finding(
                "F-CC-S22", "AR-CC-S22", "D-CC", "soft", "🟢",
                "Make execution intent explicit — 'Run X' (execute) vs. 'See X' (read as reference)",
                "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
                "Make execution intent clear: 'Run analyze_form.py to extract fields' (execute) vs. 'See analyze_form.py for the extraction algorithm' (read as reference).",
                f"{unframed_count} script references in prose lack 'Run'/'See'/'via'/'using' framing (code blocks excluded)",
                "scattered", "regex", -2))

    # AR-CC-S20: declare package dependencies (HARD)
    # Detect: skill mentions a Python lib without "pip install" or "Install required"
    py_libs_mentioned = re.findall(
        r"\b(pypdf|pdfplumber|PyMuPDF|pdf2image|openpyxl|pandas|numpy|requests|beautifulsoup4|lxml|pillow|matplotlib|reportlab|docx|python-docx)\b",
        body, re.IGNORECASE)
    if py_libs_mentioned:
        has_install_directive = bool(re.search(
            r"pip\s+install|Install required package|requirements\.txt|dependencies?:",
            body, re.IGNORECASE))
        if not has_install_directive:
            findings.append(make_finding(
                "F-CC-S20", "AR-CC-S20", "D-CC", "hard", "🔴",
                "Don't assume packages are installed — declare dependencies explicitly",
                "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
                "Don't assume packages are available. Bad: 'Use the pdf library to process the file.' Good: 'Install required package: pip install pypdf. Then use it...'",
                f"libs mentioned ({sorted(set(py_libs_mentioned))[:5]}) without install directive",
                "scattered", "code-check", -10))

    # AR-CC-S19: MCP tools fully-qualified ServerName:tool_name (HARD)
    # Detect: mentions MCP + tool reference that is NOT in Server:tool form
    mentions_mcp = bool(re.search(r"\bMCP\b|mcp__|mcpServers", body))
    if mentions_mcp:
        # Look for bare tool references like "use the X tool" without "Server:" prefix
        bare_tool_refs = re.findall(
            r"\b(?:use|invoke|call|via)\s+the\s+([a-z][\w_]+)\s+tool\b",
            body, re.IGNORECASE)
        unqualified = [t for t in bare_tool_refs if ":" not in t]
        if unqualified:
            findings.append(make_finding(
                "F-CC-S19", "AR-CC-S19", "D-CC", "hard", "🔴",
                "MCP tool references must use fully-qualified ServerName:tool_name",
                "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
                "If your Skill uses MCP (Model Context Protocol) tools, always use fully qualified tool names to avoid 'tool not found' errors. Format: ServerName:tool_name",
                f"unqualified MCP tool refs: {unqualified[:3]}",
                "scattered", "regex", -10))

    # AR-CC-S21: reference files >100 lines should have TOC (refines AR-CC-S10)
    # Applied to the skill body itself; references/ files validated separately
    if body_lines > 100:
        has_toc = bool(re.search(
            r"^#+\s*(table of contents|TOC|contents)\b|## Contents\b",
            body[:3000], re.IGNORECASE | re.MULTILINE))
        if not has_toc:
            findings.append(make_finding(
                "F-CC-S21", "AR-CC-S21", "D-CC", "soft", "🟢",
                "Files >100 lines should include a table of contents at the top",
                "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
                "For reference files longer than 100 lines, include a table of contents at the top. This ensures Claude can see the full scope of available information even when previewing with partial reads.",
                f"body is {body_lines} lines, no TOC in first 3000 chars",
                "skill body", "code-check", -3))

    return findings


# ═══════════════════════════════════════════════════════════════
# Subagent audits
# ═══════════════════════════════════════════════════════════════

def audit_subagent(path: Path, content: str, fm: dict) -> list:
    findings = []

    # AR-CC-041: required name + description
    missing = [k for k in ("name", "description") if k not in fm]
    if missing:
        findings.append(make_finding(
            "F-CC-041", "AR-CC-041", "D-CC", "critical", "🔴",
            "Required frontmatter: name AND description",
            "https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields",
            "Required: name, description.",
            f"missing: {missing}",
            "frontmatter", "code-check", -20))

    # AR-CC-043: cannot spawn other subagents
    if re.search(r"\bTask\(|@agent-\w+|@subagent-\w+", content):
        findings.append(make_finding(
            "F-CC-043", "AR-CC-043", "D-CC", "critical", "🔴",
            "Subagents CANNOT spawn other subagents",
            "https://code.claude.com/docs/en/sub-agents#choose-between-subagents-and-main-conversation",
            "Subagents cannot spawn other subagents.",
            "Task() or @agent- reference detected in subagent body",
            "body", "regex", -25))

    # AR-CC-044: pushy description with action verbs
    description = fm.get("description", "")
    has_action_verb = re.search(
        r"\b(audit|review|analyze|review|investigate|search|generate|"
        r"create|fix|optimize|validate|test|check|debug|extract|"
        r"transform|refactor|build|deploy|use proactively)\b",
        description, re.IGNORECASE)
    if description and not has_action_verb:
        findings.append(make_finding(
            "F-CC-044", "AR-CC-044", "D-CC", "high", "🟡",
            "Description is the routing signal — include action verbs and triggering contexts",
            "https://code.claude.com/docs/en/sub-agents#understand-automatic-delegation",
            "Claude uses each subagent's description to decide when to delegate tasks. To encourage proactive delegation, include phrases like 'use proactively' in your description.",
            "description lacks action verbs (audit/review/analyze/etc.) and 'use proactively' phrase",
            "frontmatter.description", "regex", -8))

    # AR-CC-042: self-contained body (heuristic — extreme brevity = under-spec)
    body_text = content.split("---\n", 2)[-1] if "---\n" in content else content
    body_words = len(body_text.split())
    if body_words < 30:
        findings.append(make_finding(
            "F-CC-042", "AR-CC-042", "D-CC", "high", "🟡",
            "Subagent body must be self-contained (no Claude Code defaults inherited)",
            "https://code.claude.com/docs/en/sub-agents#write-subagent-files",
            "Subagents receive only this system prompt (plus basic environment details), not the full Claude Code system prompt.",
            f"body has {body_words} words — likely too brief to be self-contained",
            "body", "heuristic", -7))

    return findings


# ═══════════════════════════════════════════════════════════════
# Hook config audits
# ═══════════════════════════════════════════════════════════════

def audit_hook(path: Path, content: str) -> list:
    findings = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return [make_finding(
            "F-HOOK-PARSE", "AR-CC-061", "D-CC", "critical", "🔴",
            "settings.json must be valid JSON",
            "https://code.claude.com/docs/en/hooks", "Hooks are configured in settings.json.",
            f"JSON parse failed: {e}",
            "whole-file", "code-check", -25)]

    hooks_config = data.get("hooks", {})

    canonical_events = {
        "SessionStart", "Setup", "SessionEnd", "UserPromptSubmit",
        "UserPromptExpansion", "Stop", "StopFailure", "PreToolUse", "PostToolUse",
        "PostToolUseFailure", "PermissionRequest", "PermissionDenied",
        "PostToolBatch", "Notification", "SubagentStart", "SubagentStop",
        "TeammateIdle", "TaskCreated", "TaskCompleted", "WorktreeCreate",
        "WorktreeRemove", "FileChanged", "CwdChanged", "ConfigChange",
        "InstructionsLoaded", "PreCompact", "PostCompact", "Elicitation",
        "ElicitationResult",
    }

    blocking_events = {
        "PreToolUse", "PermissionRequest", "UserPromptSubmit",
        "UserPromptExpansion", "Stop", "TaskCreated", "TaskCompleted",
        "ConfigChange", "PostToolBatch", "PreCompact", "Elicitation",
    }

    for event_name, event_hooks in hooks_config.items():
        # AR-CC-061: 26 canonical events
        if event_name not in canonical_events:
            findings.append(make_finding(
                f"F-HOOK-061-{event_name}", "AR-CC-061", "D-CC", "critical", "🔴",
                "Hook events are exactly 26 named events — no custom events",
                "https://code.claude.com/docs/en/hooks",
                "Hook events are exactly 26 named events.",
                f"non-canonical event: '{event_name}'",
                f"hooks.{event_name}", "code-check", -15))
            continue

        if not isinstance(event_hooks, list):
            continue

        for entry in event_hooks:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")

                # AR-CC-065: $CLAUDE_PROJECT_DIR usage
                if cmd:
                    has_env_var = re.search(
                        r"\$\{?CLAUDE_(PROJECT_DIR|PLUGIN_ROOT|PLUGIN_DATA)\}?", cmd)
                    is_relative = (cmd.startswith(("./", ".\\")) or
                                   (not cmd.startswith(("/", "$", "\""))
                                    and not re.match(r"^[a-zA-Z]+\s", cmd)))
                    if not has_env_var and is_relative:
                        findings.append(make_finding(
                            f"F-HOOK-065-{event_name}", "AR-CC-065", "D-CC",
                            "high", "🟡",
                            "Hook command paths must use $CLAUDE_PROJECT_DIR, never relative",
                            "https://code.claude.com/docs/en/hooks",
                            "Use $CLAUDE_PROJECT_DIR / ${CLAUDE_PLUGIN_ROOT} / ${CLAUDE_PLUGIN_DATA} instead of relative paths.",
                            f"command: {cmd[:100]}",
                            f"hooks.{event_name}", "regex", -8))

                # AR-CC-064: timeout for blocking events
                timeout = hook.get("timeout")
                if event_name in blocking_events and timeout is None:
                    findings.append(make_finding(
                        f"F-HOOK-064-{event_name}", "AR-CC-064", "D-CC",
                        "soft", "🟢",
                        "Specify hook timeout explicitly (default 600s is long for fast-fail validators)",
                        "https://code.claude.com/docs/en/hooks",
                        "Default timeout 600s.",
                        f"event '{event_name}' has no explicit timeout",
                        f"hooks.{event_name}", "code-check", -2))

    return findings


# ═══════════════════════════════════════════════════════════════
# MCP config audits
# ═══════════════════════════════════════════════════════════════

def audit_mcp(path: Path, content: str) -> list:
    findings = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return findings

    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}

    for name, cfg in servers.items():
        # AR-CC-082: HTTP > SSE
        if cfg.get("transport") == "sse":
            findings.append(make_finding(
                f"F-MCP-082-{name}", "AR-CC-082", "D-CC", "high", "🟡",
                "Prefer HTTP transport over deprecated SSE",
                "https://code.claude.com/docs/en/mcp#option-2-add-a-remote-sse-server",
                "The SSE (Server-Sent Events) transport is deprecated. Use HTTP servers instead, where available.",
                f"server '{name}' uses SSE transport",
                f"mcpServers.{name}.transport", "code-check", -8))

        # AR-CC-083: hardcoded secrets in env
        env = cfg.get("env", {})
        for key, val in env.items():
            is_secret_key = re.search(r"key|token|secret|password|api[_-]?key",
                                      key, re.IGNORECASE)
            is_literal = val and not re.match(r"^\$\{[^}]+\}$", str(val))
            if is_secret_key and is_literal:
                findings.append(make_finding(
                    f"F-MCP-AP3-{name}-{key}", "AR-CC-083", "D-CC",
                    "critical", "🔴",
                    "Hardcoded secret in .mcp.json env (use ${VAR} expansion)",
                    "https://code.claude.com/docs/en/mcp#environment-variable-expansion-in-mcp-json",
                    "Use ${VAR} or ${VAR:-default} expansion, set env var locally / via secret manager.",
                    f"server '{name}', env key '{key}' has literal secret value",
                    f"mcpServers.{name}.env.{key}", "regex", -25))

    return findings


# ═══════════════════════════════════════════════════════════════
# API config audits (NEW v1.2 — covers AR-MODEL-002/003/004/021..025,
# AR-REASON-017/018, AR-VISION-* on api payloads)
# ═══════════════════════════════════════════════════════════════

def audit_api_config(path: Path, content: str, target_model: str = None) -> list:
    """Audit a Python/JSON snippet representing an API call payload.

    Detects: prefill on 4.6+, sampling params on 4.7, effort calibration,
    max_tokens budget, prefill migration patterns when prefill is present.
    """
    findings = []

    # Try to detect target model from content if not provided
    if not target_model:
        m = re.search(r'model\s*=\s*["\']([\w-]+)', content)
        target_model = m.group(1) if m else "unknown"

    is_4_7 = bool(re.search(r"opus-4-7|claude-opus-4-7", target_model, re.IGNORECASE))
    is_4_6_plus = bool(re.search(r"opus-4-[67]|sonnet-4-6|claude-(opus|sonnet)-4-[67]",
                                  target_model, re.IGNORECASE))

    # AR-MODEL-002: prefill on 4.6+ → 400 (HARD, zero-tolerance)
    # Doctrine specifies the LAST assistant turn. We detect: the last `role:`
    # entry in the messages array is `assistant` with non-empty content.
    # Approach: find all role markers in the messages block; check the last one.
    prefill_detected = False
    msg_block = re.search(
        r'messages\s*=\s*\[(.*?)\]\s*[\),]',
        content, re.DOTALL)
    if msg_block:
        roles = re.findall(
            r'["\']role["\']\s*:\s*["\'](\w+)["\']',
            msg_block.group(1))
        if roles and roles[-1] == "assistant":
            prefill_detected = True

    if prefill_detected and is_4_6_plus:
        findings.append(make_finding(
            "F-MODEL-002", "AR-MODEL-002", "D-MODEL", "hard", "🔴",
            "Prefilled assistant message on Claude 4.6+ returns 400 error",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#migrating-away-from-prefilled-responses",
            "Starting with Claude 4.6 models and Claude Mythos Preview, prefilled responses on the last assistant turn are no longer supported.",
            f"target={target_model}, last role in messages[] is 'assistant' (prefill pattern)",
            "messages[-1]", "code-check", -20))

    # AR-MODEL-003 + AR-REASON-018: xhigh recommended for coding/agentic on 4.7
    # Accept both JSON form ("effort": "low") and Python kwarg form (effort='low')
    has_effort = (
        re.search(r'["\']effort["\']\s*:\s*["\'](\w+)', content) or
        re.search(r'\beffort\s*=\s*["\'](\w+)', content)
    )
    if is_4_7 and has_effort:
        effort_val = has_effort.group(1).lower()
        if effort_val in ("low", "medium"):
            # AR-REASON-017: effort strict on 4.7 (severity_amplification when coding)
            has_coding_signal = bool(re.search(
                r"\b(coding|code|implement|refactor|debug|agent)\b",
                content, re.IGNORECASE))
            sev = "hard" if has_coding_signal else "soft"
            triage = "🔴" if has_coding_signal else "🟢"
            impact = -10 if has_coding_signal else -3
            findings.append(make_finding(
                "F-REASON-017", "AR-REASON-017", "D-REASON", sev, triage,
                "On Opus 4.7, effort levels are strict — low/medium scope tighter (under-thinking risk on coding/agentic)",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#calibrating-effort-and-thinking-depth",
                "Claude Opus 4.7 respects effort levels strictly, especially at the low end. At low and medium, the model scopes its work to what was asked rather than going above and beyond.",
                f"effort={effort_val} on opus-4-7" + (" with coding/agentic signal (amplified)" if has_coding_signal else ""),
                "api_config.effort", "code-check", impact))

    # AR-REASON-018: xhigh as default for coding/agentic
    if is_4_7 and has_effort:
        has_coding = bool(re.search(r"\b(coding|agent|tool[- ]use)\b", content, re.IGNORECASE))
        if has_coding and has_effort.group(1).lower() not in ("xhigh", "high", "max"):
            findings.append(make_finding(
                "F-REASON-018", "AR-REASON-018", "D-REASON", "soft", "🟢",
                "On Opus 4.7, start with xhigh effort for coding/agentic; minimum high for intelligence-sensitive",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#calibrating-effort-and-thinking-depth",
                "Start with the new xhigh effort level for coding and agentic use cases, and use a minimum of high effort for most intelligence-sensitive use cases.",
                f"effort={has_effort.group(1)} below recommended xhigh/high for coding workload",
                "api_config.effort", "code-check", -3))

    # AR-MODEL-004: max_tokens >=64k at max/xhigh
    has_max_tokens = re.search(r"max_tokens\s*=\s*(\d+)", content)
    if is_4_7 and has_effort and has_max_tokens:
        eff = has_effort.group(1).lower()
        mt = int(has_max_tokens.group(1))
        if eff in ("max", "xhigh") and mt < 64000:
            findings.append(make_finding(
                "F-MODEL-004", "AR-MODEL-004", "D-MODEL", "soft", "🟢",
                "On Opus 4.7 at max/xhigh effort, set max_tokens >= 64k",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#calibrating-effort-and-thinking-depth",
                "If you are running Claude Opus 4.7 at max or xhigh effort, set a large max output token budget. We recommend starting at 64k tokens.",
                f"effort={eff}, max_tokens={mt} (< 64000 recommended)",
                "api_config.max_tokens", "code-check", -3))

    # AR-MODEL-021..025: prefill migration patterns — collapsed into ONE Open
    # Question with 5 options. Avoids polluting the scorecard with 5 sub-findings
    # that share identical context. Operator picks one pattern; LLM judges fit.
    if prefill_detected and is_4_6_plus:
        findings.append(make_finding(
            "F-MODEL-021-25", "AR-MODEL-021..025", "D-MODEL", "soft", "❓",
            "Prefill migration: 5 canonical patterns available — operator picks one",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#migrating-away-from-prefilled-responses",
            "Migration patterns from the prefill-deprecation section: Structured Outputs / direct preamble instruction / direct refusal prompting / continuation-as-user-message / context-hydration via tools.",
            f"emitted because AR-MODEL-002 fired; 5 migration options to evaluate",
            "messages[-1]", "code-check", 0,  # zero score impact — Open Question
            requires_pass2_grade=True,
            open_question=True,
            options=[
                {"id": "AR-MODEL-021", "name": "Structured Outputs", "for": "schema constraint (was: prefilled JSON)"},
                {"id": "AR-MODEL-022", "name": "Direct system-prompt instruction", "for": "preamble skip (was: 'Here is the requested...')"},
                {"id": "AR-MODEL-023", "name": "Direct user prompting", "for": "refusal steering (was: prefilled refusal nudge — no longer needed)"},
                {"id": "AR-MODEL-024", "name": "Continuation as user message", "for": "resume after interruption (was: prefilled continuation)"},
                {"id": "AR-MODEL-025", "name": "User-turn injection or tool-mediated retrieval", "for": "context hydration (was: prefilled reminders)"},
            ],
            group="prefill-migration"))

    # AP-15: sampling params on Opus 4.7 → 400 (HARD)
    if is_4_7:
        for param in ("temperature", "top_p", "top_k"):
            m = re.search(rf"\b{param}\s*=\s*([\d.]+)", content)
            if m:
                findings.append(make_finding(
                    f"F-AP-15-{param}", "AR-MODEL-002", "D-MODEL", "hard", "🔴",
                    f"Sampling param '{param}' on Opus 4.7 → 400 error",
                    "https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7",
                    f"{param}, top_p, top_k → 400 error (sampling params not accepted) on opus-4-7",
                    f"{param}={m.group(1)} on opus-4-7",
                    f"api_config.{param}", "code-check", -15))

    # AR-VISION-001: images BEFORE text in user message
    # Approach: parse content array sequence (image vs text type entries) and
    # check first-occurrence ordering. Doctrine: "images come BEFORE text" —
    # so the first content block of a user-message multimodal payload should
    # be an image, not text. We only flag when images exist (no false positive
    # on text-only prompts).
    type_seq = re.findall(r'["\']type["\']\s*:\s*["\'](image|text)["\']', content)
    if "image" in type_seq:
        # Find the first content block in any user-role message
        user_msg_block = re.search(
            r'["\']role["\']\s*:\s*["\']user["\'].*?["\']content["\']\s*:\s*\[(.*?)\]',
            content, re.DOTALL)
        if user_msg_block:
            local_seq = re.findall(
                r'["\']type["\']\s*:\s*["\'](image|text)["\']',
                user_msg_block.group(1))
            if local_seq and local_seq[0] == "text" and "image" in local_seq:
                findings.append(make_finding(
                    "F-VISION-001", "AR-VISION-001", "D-VISION", "soft", "🟢",
                    "Place images BEFORE text in user message",
                    "https://platform.claude.com/docs/en/build-with-claude/vision",
                    "Claude works best when images come before text.",
                    f"user-message content[0] is text, image follows (sequence: {local_seq[:5]})",
                    "user message content[0]", "code-check", -3))

    return findings


# ═══════════════════════════════════════════════════════════════
# System/User prompt audits (covers ALL artifact_types not above)
# ═══════════════════════════════════════════════════════════════

def audit_prompt(path: Path, content: str) -> list:
    """Generic prompt audit — applies to system_prompt, user_prompt, workflow."""
    findings = []
    char_count = len(content)
    line_count = content.count("\n") + 1

    # AR-CLAR-006: positive over negative
    negative_count = len(re.findall(r"\b(do not|don't|never|no\b)\b", content, re.IGNORECASE))
    positive_alt_count = len(re.findall(r"\binstead\b|\brather\b", content, re.IGNORECASE))
    if negative_count > 5 and positive_alt_count < negative_count // 2:
        findings.append(make_finding(
            "F-CLAR-006", "AR-CLAR-006", "D-CLAR", "hard", "🔴",
            "Tell what to DO instead of what NOT to do",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#control-the-format-of-responses",
            "Tell Claude what to do instead of what not to do.",
            f"{negative_count} negative imperatives, {positive_alt_count} positive alts",
            "scattered", "regex", -10))

    # AR-CLAR-011: vague action language
    vague_action = re.findall(
        r"\b(can you|could you|would you|maybe|perhaps|consider)\s+(suggest|review|look at|check)\b",
        content, re.IGNORECASE)
    if vague_action:
        findings.append(make_finding(
            "F-CLAR-011", "AR-CLAR-011", "D-CLAR", "hard", "🔴",
            "Be explicit when you want action; vague phrasing produces suggestions",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#tool-usage",
            "If you say 'can you suggest some changes,' Claude will sometimes provide suggestions rather than implementing them.",
            f"vague-action phrases: {[' '.join(m) for m in vague_action[:3]]}",
            "scattered", "regex", -10))

    # AR-STRUCT-008: examples without <example> tags
    has_loose_example = re.search(r"^example:\s*$|^\*\*example\*\*", content,
                                   re.MULTILINE | re.IGNORECASE)
    has_example_tags = re.search(r"<example>|<examples>", content)
    if has_loose_example and not has_example_tags:
        findings.append(make_finding(
            "F-STRUCT-008", "AR-STRUCT-008", "D-STRUCT", "hard", "🔴",
            "Wrap examples in <example> tags to distinguish from instructions",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#use-examples-effectively",
            "Wrap examples in <example> tags (multiple examples in <examples> tags) so Claude can distinguish them from instructions.",
            "examples present without <example>/<examples> wrapping",
            "scattered", "regex", -10))

    # AR-STRUCT-001: complex prompt without XML structure
    has_multiple_sections = len(re.findall(r"^##\s+", content, re.MULTILINE))
    has_xml_tags = re.search(r"<[a-z_]+>", content)
    if char_count > 2000 and has_multiple_sections >= 4 and not has_xml_tags:
        findings.append(make_finding(
            "F-STRUCT-001", "AR-STRUCT-001", "D-STRUCT", "soft", "🟡",
            "Use XML tags to structure complex prompts mixing instructions, context, examples",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#structure-prompts-with-xml-tags",
            "XML tags help Claude parse complex prompts unambiguously, especially when your prompt mixes instructions, context, examples, and variable inputs.",
            f"prompt is {char_count} chars, {has_multiple_sections} sections, no XML tags",
            "whole-file", "heuristic", -6))

    # AR-MODEL-008: placeholders in prompt
    placeholder_pattern = re.search(
        r"<insert[_ ](?:value|name|here)>|<TODO>|<FILL[_ ]IN>|\bxxx+\b|<placeholder>",
        content, re.IGNORECASE)
    if placeholder_pattern:
        findings.append(make_finding(
            "F-MODEL-008", "AR-MODEL-008", "D-MODEL", "hard", "🔴",
            "Never use placeholders or guess missing parameters in tool calls",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices",
            "Never use placeholders or guess missing parameters in tool calls.",
            f"placeholder detected: '{placeholder_pattern.group(0)}'",
            "scattered", "regex", -12))

    # AR-CLAR-013: factual prompts should permit "I don't know"
    is_factual = re.search(
        r"\b(what is|who is|when did|how many|explain|describe|tell me about)\b",
        content[:500], re.IGNORECASE)
    permits_dontknow = re.search(
        r"\b(don't know|i don't know|unsure|not sure|admit uncertainty)\b",
        content, re.IGNORECASE)
    if is_factual and not permits_dontknow and char_count > 300:
        findings.append(make_finding(
            "F-CLAR-013", "AR-CLAR-013", "D-CLAR", "hard", "🔴",
            "Allow Claude to admit uncertainty in factual prompts",
            "https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations",
            "Allow Claude to say 'I don't know': Explicitly give Claude permission to admit uncertainty.",
            "factual prompt without 'I don't know' permission clause",
            "whole-file", "regex", -10))

    # AR-EVAL-001: verification embedded
    asks_for_artifact = re.search(
        r"\b(write|create|generate|implement|build|produce|design)\b",
        content, re.IGNORECASE)
    has_verification = re.search(
        r"\b(test|verify|check|validate|ensure that|self-check|expected output)\b",
        content, re.IGNORECASE)
    if asks_for_artifact and not has_verification and char_count > 300:
        findings.append(make_finding(
            "F-EVAL-001", "AR-EVAL-001", "D-EVAL", "hard", "🔴",
            "Embed verification criteria in prompt — single highest-leverage thing",
            "https://code.claude.com/docs/en/best-practices",
            "Include tests, screenshots, or expected outputs so Claude can check itself. This is the single highest-leverage thing you can do.",
            "prompt requests artifact creation but lacks test/verify/check criterion",
            "whole-file", "heuristic", -10))

    # ───── v1.2 currency-patch detectors (E2) ─────

    # AR-MODEL-014: legacy "after N tool calls, summarize" scaffolding (Opus 4.7)
    legacy_scaffold = re.search(
        r"\b(?:after\s+every\s+\d+|every\s+\d+)\s+(?:tool\s+calls?|actions?|steps?)\b.*?(?:summari[sz]e|status|update|report)",
        content, re.IGNORECASE | re.DOTALL)
    if legacy_scaffold:
        findings.append(make_finding(
            "F-MODEL-014", "AR-MODEL-014", "D-MODEL", "soft", "🟢",
            "Remove legacy 'after N tool calls, summarize' scaffolding — Opus 4.7 emits higher-quality progress updates by default",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#user-facing-progress-updates",
            "Claude Opus 4.7 provides more regular, higher-quality updates to the user throughout long agentic traces. If you've added scaffolding to force interim status messages ('After every 3 tool calls, summarize progress'), try removing it.",
            f"legacy scaffolding phrase: '{legacy_scaffold.group(0)[:80]}'",
            "scattered", "regex", -3))

    # AR-MODEL-015: subagent guidance missing (Opus 4.7, soft)
    # Only fires on artifacts that ORCHESTRATE subagents (system_prompt, agent,
    # claude_md). Suppressed on subagent files themselves (they cannot spawn other
    # subagents per AR-CC-043 — guidance would be nonsensical).
    is_subagent_artifact = bool(re.search(
        r"^---\s*$.*?^name:.*?^description:",
        content[:500], re.MULTILINE | re.DOTALL))
    mentions_subagent = re.search(
        r"\b(spawn|invoke|delegate to)\s+(?:a\s+|multiple\s+)?sub[\s-]?agents?\b|Task\(",
        content, re.IGNORECASE)
    if mentions_subagent and not is_subagent_artifact:
        has_guidance = re.search(
            r"\b(do not spawn|don't spawn|spawn (?:a |multiple )?subagent[s]? (?:when|for|in the same))\b",
            content, re.IGNORECASE)
        if not has_guidance:
            findings.append(make_finding(
                "F-MODEL-015", "AR-MODEL-015", "D-MODEL", "soft", "🟢",
                "Provide explicit guidance on when subagents are/aren't desirable (Opus 4.7 spawns fewer by default)",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#controlling-subagent-spawning",
                "Claude Opus 4.7 tends to spawn fewer subagents by default. However, this behavior is steerable through prompting; give Claude Opus 4.7 explicit guidance around when subagents are desirable.",
                "subagent orchestration mentioned without explicit when-to-spawn guidance",
                "scattered", "regex", -3))

    # AR-MODEL-016: design defaults negation without concrete alternative (Opus 4.7)
    has_design_signal = bool(re.search(
        r"\b(landing page|frontend|design|UI|color (?:scheme|palette)|typography|CSS)\b",
        content, re.IGNORECASE))
    if has_design_signal:
        has_negation = re.search(
            r"\b(?:don't|do not|avoid|no)\s+(?:use\s+)?(?:cream|purple|gradient|warm|serif|terracotta)\b",
            content, re.IGNORECASE)
        has_concrete_palette = re.search(r"#[0-9A-Fa-f]{3,6}\b", content)
        has_propose_options = re.search(
            r"\bpropose\s+\d+\s+(?:distinct\s+)?(?:visual\s+)?direction",
            content, re.IGNORECASE)
        if has_negation and not (has_concrete_palette or has_propose_options):
            findings.append(make_finding(
                "F-MODEL-016", "AR-MODEL-016", "D-MODEL", "soft", "🟢",
                "Generic design negation bounces on Opus 4.7 — specify concrete alternative or ask model to propose options",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#design-and-frontend-defaults",
                "This default is persistent. Generic instructions ('don't use cream,' 'make it clean and minimal') tend to shift the model to a different fixed palette rather than producing variety.",
                f"design negation '{has_negation.group(0)}' without concrete palette or propose-options pattern",
                "scattered", "regex", -3))

    # AR-MODEL-018: code-review harness regression (Opus 4.7, HARD)
    has_review_signal = bool(re.search(
        r"\b(code review|review prompt|find bugs|review(?:ing)? (?:the |this )?(?:code|PR|pull request)|code-review harness)\b",
        content, re.IGNORECASE))
    if has_review_signal:
        recall_killer = re.search(
            r"\b(?:only (?:report|surface|flag) (?:high[- ]severity|critical|important)|be conservative|don't nitpick|skip nits)\b",
            content, re.IGNORECASE)
        if recall_killer:
            findings.append(make_finding(
                "F-MODEL-018", "AR-MODEL-018", "D-MODEL", "hard", "🔴",
                "Code-review harness regression: 'be conservative'/'only high-severity' reduces recall on 4.7 — use 'report every issue, downstream filter ranks them'",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#code-review-harnesses",
                "When a review prompt says things like 'only report high-severity issues,' 'be conservative,' or 'don't nitpick,' Claude Opus 4.7 may follow that instruction more faithfully than earlier models did... Report every issue you find, including ones you are uncertain about or consider low-severity.",
                f"recall-killing phrase: '{recall_killer.group(0)}'",
                "scattered", "regex", -12))

    # AR-REASON-019: adaptive thinking steerable (hybrid candidate, Pass-1 emits candidate)
    mentions_thinking = re.search(r"\b(thinking|adaptive thinking)\b", content, re.IGNORECASE)
    if mentions_thinking:
        has_steering = re.search(
            r"\b(respond directly|when in doubt|only when (?:it will|the))\b",
            content, re.IGNORECASE)
        if not has_steering and len(content) > 1500:
            findings.append(make_finding(
                "F-REASON-019", "AR-REASON-019", "D-REASON", "soft", "🟢",
                "[Pass-2 candidate] Adaptive thinking mentioned without steering — verify whether steering is needed for workload",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#calibrating-effort-and-thinking-depth",
                "The triggering behavior for adaptive thinking is steerable. If you find the model thinking more often than you'd like — which can happen with large or complex system prompts — add guidance to steer it.",
                "thinking mentioned in long prompt without steering verbs (respond directly/when in doubt)",
                "scattered", "hybrid", -2,
                requires_pass2_grade=True))

    # ───── Reclassifications from §13 of the audit matrix ─────

    # AR-STRUCT-006: XML format indicators (soft, regex)
    asks_for_format = re.search(
        r"\b(format(?:ted)?\s+(?:as|in|like)|wrap.*tags?|inside.*tags?|return\s+(?:as|in)\s+\w+)\b",
        content, re.IGNORECASE)
    has_xml_format_indicator = re.search(r"<[a-z][\w_]*>(?!\s*$)", content)
    if asks_for_format and not has_xml_format_indicator and char_count > 500:
        findings.append(make_finding(
            "F-STRUCT-006", "AR-STRUCT-006", "D-STRUCT", "soft", "🟢",
            "Use XML format indicators (e.g., <smoothly_flowing_prose_paragraphs>) for output structure",
            "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#control-the-format-of-responses",
            "Use XML format indicators.",
            "format request without XML tag wrapping",
            "scattered", "regex", -2))

    # AR-EXAMPLE-005: <thinking> tags inside few-shot examples (soft, code-check)
    example_blocks = re.findall(r"<example>(.*?)</example>", content, re.DOTALL)
    if example_blocks:
        thinking_in_examples = sum(1 for blk in example_blocks if re.search(r"<thinking>", blk))
        if thinking_in_examples == 0 and len(example_blocks) >= 2:
            findings.append(make_finding(
                "F-EXAMPLE-005", "AR-EXAMPLE-005", "D-EXAMPLE", "soft", "🟢",
                "Use <thinking> tags inside few-shot examples to demonstrate reasoning patterns",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#leverage-thinking",
                "Multishot examples work with thinking. Use <thinking> tags inside your few-shot examples to show Claude the reasoning pattern.",
                f"{len(example_blocks)} <example> blocks present, none contain <thinking>",
                "scattered", "code-check", -2))

    # AR-EXAMPLE-008: too many implementation alternatives (soft, regex)
    multi_alt_pattern = re.search(
        r"(?:You can use|use either|use one of|or you can use|alternatively)\s+([\w]+)(?:\s*,\s*(?:or\s+)?[\w]+){2,}",
        content, re.IGNORECASE)
    if multi_alt_pattern:
        findings.append(make_finding(
            "F-EXAMPLE-008", "AR-EXAMPLE-008", "D-EXAMPLE", "soft", "🟢",
            "Provide a default with escape hatch instead of listing many alternatives",
            "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
            "Don't present multiple approaches unless necessary.",
            f"3+ alternatives offered: '{multi_alt_pattern.group(0)[:80]}'",
            "scattered", "regex", -2))

    # AR-REASON-007: chain-of-thought verification language (soft, regex)
    asks_for_complex = re.search(
        r"\b(analy[sz]e|reason about|figure out|determine|diagnose|investigate|debug)\b",
        content, re.IGNORECASE)
    has_step_by_step = re.search(
        r"\b(step[- ]by[- ]step|reason through|think through|explain (?:your )?reasoning|walk (?:me |through))\b",
        content, re.IGNORECASE)
    if asks_for_complex and not has_step_by_step and char_count > 500:
        findings.append(make_finding(
            "F-REASON-007", "AR-REASON-007", "D-REASON", "soft", "🟢",
            "Ask Claude to explain reasoning step-by-step before final answer for complex analysis",
            "https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations",
            "Chain-of-thought verification: Ask Claude to explain its reasoning step-by-step before giving a final answer.",
            "complex-analysis request without step-by-step language",
            "scattered", "regex", -2))

    # AR-CONTEXT-003: quote-first instruction for long-doc tasks (soft, regex)
    # Strip code blocks first — <documents> schema in code blocks is documentation,
    # not a real long-doc payload (this skill itself teaches the schema).
    content_no_code = re.sub(r"```[\s\S]*?```", "", content)
    has_long_doc_signal = re.search(
        r"<documents?>|<document_content>|\{\{[A-Z_]+\}\}",
        content_no_code)
    if has_long_doc_signal:
        has_quote_first = re.search(
            r"\b(quote (?:first|relevant|word[- ]for[- ]word)|<quotes>|extract.*quotes?)\b",
            content_no_code, re.IGNORECASE)
        if not has_quote_first:
            findings.append(make_finding(
                "F-CONTEXT-003", "AR-CONTEXT-003", "D-CONTEXT", "soft", "🟢",
                "For long documents, ask Claude to quote relevant parts FIRST before performing the task",
                "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#long-context-prompting",
                "Ground responses in quotes: For long document tasks, ask Claude to quote relevant parts of the documents first before carrying out its task.",
                "long-doc structure detected (in prose, not code) without quote-first instruction",
                "scattered", "regex", -3))

    # AR-AGENT-009: parallel tool/subagent counts mentioned (soft)
    has_parallel_signal = re.search(
        r"\b(parallel\s+tools?|parallel\s+subagents?|in parallel|concurrent(?:ly)?)\b",
        content, re.IGNORECASE)
    if has_parallel_signal:
        has_count = re.search(
            r"\b(?:3\+|3-5|3 to 5|3,\s*4,?\s*(?:or|and)?\s*5|multiple)\s+(?:tools?|subagents?|calls?)\b",
            content, re.IGNORECASE)
        if not has_count:
            findings.append(make_finding(
                "F-AGENT-009", "AR-AGENT-009", "D-AGENT", "soft", "🟢",
                "Specify parallel-call counts explicitly (3+ tools, 3-5 subagents)",
                "https://www.anthropic.com/engineering/multi-agent-research-system",
                "Subagents use 3+ tools in parallel and lead agent spins up 3-5 subagents in parallel rather than serially.",
                "parallel mentioned without explicit count guidance",
                "scattered", "regex", -2))

    return findings


# ═══════════════════════════════════════════════════════════════
# Frontmatter extraction
# ═══════════════════════════════════════════════════════════════

def extract_frontmatter(content: str) -> dict:
    if not content.lstrip().startswith("---\n"):
        return {}
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return {}
    fm_text = parts[1]
    fm = {}
    current_key = None
    current_val = []
    for line in fm_text.splitlines():
        m = re.match(r"^([a-z][a-z0-9_-]*)\s*:\s*(.*)$", line)
        if m:
            if current_key:
                fm[current_key] = " ".join(current_val).strip()
            current_key = m.group(1)
            current_val = [m.group(2).strip()] if m.group(2).strip() else []
        elif current_key and line.strip():
            current_val.append(line.strip())
    if current_key:
        fm[current_key] = " ".join(current_val).strip()
    return fm


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Pass 1 mechanical audit (regex + code-check)")
    parser.add_argument("path", type=Path)
    parser.add_argument("--type", required=True, choices=[
        "claude_md", "skill", "slash_command", "subagent",
        "hook_config", "mcp_config", "system_prompt", "user_prompt",
        "api_config", "workflow", "unknown",
    ])
    parser.add_argument("--target-model", default=None,
                        help="Target Claude model (e.g., opus-4-7). Used to gate model-specific findings.")
    args = parser.parse_args()

    if not args.path.exists():
        print(json.dumps({"error": f"path not found: {args.path}"}), file=sys.stderr)
        sys.exit(1)

    content = args.path.read_text(encoding="utf-8", errors="replace")
    fm = extract_frontmatter(content)

    findings = []
    if args.type == "claude_md":
        findings = audit_claude_md(args.path, content, fm)
        findings.extend(audit_prompt(args.path, content))
    elif args.type in ("skill", "slash_command"):
        findings = audit_skill(args.path, content, fm)
    elif args.type == "subagent":
        findings = audit_subagent(args.path, content, fm)
        findings.extend(audit_prompt(args.path, content))
    elif args.type == "hook_config":
        findings = audit_hook(args.path, content)
    elif args.type == "mcp_config":
        findings = audit_mcp(args.path, content)
    elif args.type == "api_config":
        findings = audit_api_config(args.path, content, args.target_model)
    elif args.type in ("system_prompt", "user_prompt", "workflow"):
        findings = audit_prompt(args.path, content)
        # If api_config signal present in a prompt artifact, also run api audits
        if re.search(r'\bclient\.messages\.create|claude-(?:opus|sonnet|haiku)-', content):
            findings.extend(audit_api_config(args.path, content, args.target_model))
    else:
        findings = []

    # Honest coverage caveat (per gaps.md)
    output = {
        "path": str(args.path),
        "type": args.type,
        "target_model": args.target_model or "unspecified",
        "pass": "mechanical (pass 1)",
        "rules_version": "1.2",
        "findings_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
