#!/usr/bin/env python3
"""
optimize.py — v1.2 (E3 Snippets Integration)

USO: python optimize.py <artifact_path> --findings <findings.json>
                       [--type <artifact_type>] [--apply]
QUANDO USAR: P4 (OPTIMIZE) — gera surgical diffs por finding com source_url cited.
OUTPUT: JSON {diffs: [...], snippet_patches: [...], unfixable: [...], summary}.

Detection method routing:
  - regex/code-check          → deterministic diff (auto-fixable)
  - heuristic/llm-judge       → template diff (operator completes)
  - any rule with snippet_id  → snippet patch (verbatim insertion from
                                 assets/snippets/<name>.md, no paraphrase)

Snippet patches are preferred over template diffs when available — they carry
byte-exact Anthropic-canonical text and minimize voice drift (per H3).

Sem --apply: apenas propõe diffs (operator é o editor — never-rewrite-rule).
Com --apply: escreve em <path>.optimized.<ext> (NUNCA sobrescreve original).
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Snippet index loaded lazily (yaml is optional dep — fall back to empty index)
_SNIPPET_INDEX = None
_SNIPPETS_DIR = Path(__file__).parent.parent / "assets" / "snippets"


def load_snippet_index() -> dict:
    """Load assets/snippets/index.yaml. Returns empty dict if unavailable."""
    global _SNIPPET_INDEX
    if _SNIPPET_INDEX is not None:
        return _SNIPPET_INDEX
    try:
        import yaml  # type: ignore
    except ImportError:
        _SNIPPET_INDEX = {}
        return _SNIPPET_INDEX
    idx_path = _SNIPPETS_DIR / "index.yaml"
    if not idx_path.exists():
        _SNIPPET_INDEX = {}
        return _SNIPPET_INDEX
    _SNIPPET_INDEX = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
    return _SNIPPET_INDEX


def get_snippets_for_rule(rule_id: str, artifact_type: str = None) -> list:
    """Return list of snippet filenames applicable to rule_id, filtered by
    artifact_type via suppress_in_types map.
    """
    idx = load_snippet_index()
    candidates = idx.get("snippets_by_rule", {}).get(rule_id, []) or []
    if not artifact_type:
        return candidates
    suppress_map = idx.get("suppress_in_types", {})
    return [s for s in candidates if artifact_type not in suppress_map.get(s, [])]


def extract_verbatim_from_snippet(snippet_path: Path) -> str:
    """Pull the verbatim block from a snippet file. Returns the first ```text
    block content (the canonical insertion text)."""
    if not snippet_path.exists():
        return ""
    text = snippet_path.read_text(encoding="utf-8")
    m = re.search(r"```text\n(.*?)\n```", text, re.DOTALL)
    return m.group(1) if m else ""


def make_snippet_patch(rule_id: str, snippet_name: str, source_url: str,
                        verbatim_quote: str, location: str, severity: str,
                        expected_delta: int) -> dict:
    """Build a snippet-patch record (verbatim insertion, low voice drift)."""
    snippet_path = _SNIPPETS_DIR / snippet_name
    verbatim_block = extract_verbatim_from_snippet(snippet_path)
    return {
        "rule_id": rule_id,
        "patch_type": "snippet_insert",
        "snippet": snippet_name,
        "snippet_path": f"assets/snippets/{snippet_name}",
        "source_url": source_url,
        "verbatim_quote": verbatim_quote,
        "location": location,
        "insert_text": verbatim_block,
        "severity": severity,
        "expected_score_delta": expected_delta,
        "voice_drift_estimate": "low",  # canonical doc text
        "regression_risk": "low",
        "deterministic": True,
        "note": (f"Verbatim insertion from {snippet_name}. "
                 "Operator may adapt wording but preserve structural intent."),
    }


def make_diff(rule_id: str, source_url: str, verbatim_quote: str,
              location: str, before: str, after: str, severity: str,
              expected_delta: int, voice_drift: str = "low",
              regression_risk: str = "low", deterministic: bool = True,
              note: str = "") -> dict:
    return {
        "rule_id": rule_id,
        "source_url": source_url,
        "verbatim_quote": verbatim_quote,
        "location": location,
        "before": before,
        "after": after,
        "severity": severity,
        "expected_score_delta": expected_delta,
        "voice_drift_estimate": voice_drift,
        "regression_risk": regression_risk,
        "deterministic": deterministic,
        "note": note,
    }


def fix_skill_name(content: str, current_name: str) -> str:
    """Convert skill name to valid regex form."""
    fixed = current_name.lower()
    fixed = re.sub(r"[_\s]+", "-", fixed)
    fixed = re.sub(r"[^a-z0-9-]", "", fixed)
    fixed = fixed[:64]
    if not fixed:
        fixed = "renamed-skill"
    return fixed


def fix_third_person(description: str) -> str:
    """Best-effort first-person → third-person rewrite."""
    rules = [
        (r"\bI can help (?:you )?", "Helps "),
        (r"\bI help (?:you )?", "Helps "),
        (r"\bI will ", "Will "),
        (r"\bI'll ", "Will "),
        (r"\bI am ", "Is "),
        (r"\bWe will ", "Will "),
        (r"\bWe help ", "Helps "),
        (r"\bWe are ", "Is "),
        (r"\byou can use this skill\b", "use this skill"),
        (r"\byou can use me\b", "use this skill"),
        (r"\byou can ask me\b", "use this skill"),
    ]
    out = description
    for pat, repl in rules:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def fix_backslash_paths(content: str) -> tuple:
    """Replace Windows-style backslashes with forward slashes in paths."""
    pattern = re.compile(r"([A-Z]):\\((?:[^\s\\<>\"|*?]+\\?)+)")
    matches = list(pattern.finditer(content))
    new_content = content
    diffs = []
    for m in matches:
        original = m.group(0)
        # Convert C:\Users\... to C:/Users/...
        fixed = original.replace("\\", "/")
        new_content = new_content.replace(original, fixed)
        diffs.append((original, fixed))
    return new_content, diffs


def remove_negative_rephrase(content: str) -> tuple:
    """Suggest positive rephrasings of negative imperatives. Returns content + suggestions."""
    suggestions = []
    # We don't auto-fix prose — just identify and suggest
    pattern = re.compile(r"^(\s*[-*\d.]?\s*)(Do not|Don't|Never)\s+([a-z][\w ]*[.!?:])",
                          re.MULTILINE | re.IGNORECASE)
    for m in pattern.finditer(content):
        prefix, neg, rest = m.group(1), m.group(2), m.group(3)
        original_line = m.group(0)
        # Construct a positive template
        verb_phrase = rest.rstrip(".!?:").strip()
        # Heuristic positive: "Always [opposite]" or "Ensure [reverse]"
        positive_template = (
            f"{prefix}When tempted to {verb_phrase.lower()}, instead [POSITIVE_ACTION]. "
            f"[Operator: provide concrete positive instruction.]"
        )
        suggestions.append((original_line.strip(), positive_template.strip()))
    return suggestions


def generate_diffs(content: str, findings: list, fm: dict,
                    artifact_type: str = None) -> tuple:
    """
    Returns (diffs, snippet_patches, unfixable_findings).
    diffs: list of deterministic / template diff records.
    snippet_patches: list of verbatim-insertion records from assets/snippets/.
    unfixable: findings requiring qualitative reasoning (Pass 2).

    Snippet patches are preferred when a finding's rule_id maps to a canonical
    snippet (per assets/snippets/index.yaml). Template diffs are only emitted
    for rules that have NO matching snippet AND NO inline auto-fix branch.
    """
    diffs = []
    snippet_patches = []
    unfixable = []
    modified_content = content

    for f in findings:
        rule_id = f.get("rule_id", "")
        detection = f.get("detection_method", "")
        severity = f.get("severity", "soft")

        # Snippet patch path: rule has a canonical snippet → emit verbatim patch
        # in addition to (or instead of) inline diff. Snippets are preferred for
        # rules where the doc provides a canonical XML block.
        applicable_snippets = get_snippets_for_rule(rule_id, artifact_type)
        for snippet_name in applicable_snippets:
            impact_map = {"hard": 12, "soft": 5, "critical": 15}
            snippet_patches.append(make_snippet_patch(
                rule_id=rule_id,
                snippet_name=snippet_name,
                source_url=f.get("source_url", ""),
                verbatim_quote=f.get("verbatim_quote", ""),
                location=f.get("location", "scattered"),
                severity=severity,
                expected_delta=impact_map.get(severity, 5),
            ))

        # AR-CC-022: skill name regex
        if rule_id == "AR-CC-022":
            current = fm.get("name", "")
            fixed = fix_skill_name(content, current)
            diffs.append(make_diff(
                rule_id=rule_id,
                source_url=f.get("source_url", ""),
                verbatim_quote=f.get("verbatim_quote", ""),
                location="frontmatter.name",
                before=f"name: {current}",
                after=f"name: {fixed}",
                severity=severity,
                expected_delta=20,
                voice_drift="low",
                regression_risk="low",
                deterministic=True,
                note="Auto-fix: lowercase, hyphens for separators, strip non-canonical chars",
            ))

        # AR-CC-S02: third-person description
        elif rule_id == "AR-CC-S02":
            current = fm.get("description", "")
            fixed = fix_third_person(current)
            diffs.append(make_diff(
                rule_id=rule_id,
                source_url=f.get("source_url", ""),
                verbatim_quote=f.get("verbatim_quote", ""),
                location="frontmatter.description",
                before=f"description: {current}",
                after=f"description: {fixed}",
                severity=severity,
                expected_delta=15,
                voice_drift="low",
                regression_risk="low",
                deterministic=True,
                note="Auto-fix: rule-based pronoun rewrite. Review for tone preservation.",
            ))

        # AR-CC-S06: forward slashes only
        elif rule_id == "AR-CC-S06":
            new_content, path_changes = fix_backslash_paths(modified_content)
            for original, fixed in path_changes:
                diffs.append(make_diff(
                    rule_id=rule_id,
                    source_url=f.get("source_url", ""),
                    verbatim_quote=f.get("verbatim_quote", ""),
                    location="scattered (path strings)",
                    before=original,
                    after=fixed,
                    severity=severity,
                    expected_delta=10,
                    voice_drift="low",
                    regression_risk="low",
                    deterministic=True,
                    note="Auto-fix: backslash → forward slash",
                ))
            modified_content = new_content

        # AR-CLAR-006: positive over negative
        elif rule_id == "AR-CLAR-006":
            suggestions = remove_negative_rephrase(content)
            for original, template in suggestions[:5]:  # cap at 5 suggestions
                diffs.append(make_diff(
                    rule_id=rule_id,
                    source_url=f.get("source_url", ""),
                    verbatim_quote=f.get("verbatim_quote", ""),
                    location="prose line",
                    before=original,
                    after=template,
                    severity=severity,
                    expected_delta=2,
                    voice_drift="medium",
                    regression_risk="medium",
                    deterministic=False,
                    note="Template: operator must replace [POSITIVE_ACTION] with concrete instruction",
                ))

        # AR-CC-061: custom hook event
        elif rule_id == "AR-CC-061":
            evidence = f.get("evidence", "")
            event_match = re.search(r"non-canonical event: '([^']+)'", evidence)
            if event_match:
                event = event_match.group(1)
                diffs.append(make_diff(
                    rule_id=rule_id,
                    source_url=f.get("source_url", ""),
                    verbatim_quote=f.get("verbatim_quote", ""),
                    location=f"hooks.{event}",
                    before=f'"{event}": [...]',
                    after=f'/* DELETE this block — "{event}" is not a canonical event. '
                          f'Use one of the 26 valid events. */',
                    severity=severity,
                    expected_delta=15,
                    voice_drift="low",
                    regression_risk="low",
                    deterministic=True,
                    note=f"Operator must remove or rename '{event}' to canonical event",
                ))

        # AR-CC-065: relative hook path
        elif rule_id == "AR-CC-065":
            evidence = f.get("evidence", "")
            cmd_match = re.search(r"command: (.+)", evidence)
            if cmd_match:
                cmd = cmd_match.group(1).strip()
                # Replace ./ with $CLAUDE_PROJECT_DIR/
                fixed_cmd = re.sub(r"^\.[\\/]", "$CLAUDE_PROJECT_DIR/", cmd)
                diffs.append(make_diff(
                    rule_id=rule_id,
                    source_url=f.get("source_url", ""),
                    verbatim_quote=f.get("verbatim_quote", ""),
                    location=f.get("location", ""),
                    before=f'"command": "{cmd}"',
                    after=f'"command": "{fixed_cmd}"',
                    severity=severity,
                    expected_delta=8,
                    voice_drift="low",
                    regression_risk="low",
                    deterministic=True,
                    note="Auto-fix: prepend $CLAUDE_PROJECT_DIR/",
                ))

        # AR-CC-083: hardcoded MCP secret
        elif rule_id == "AR-CC-083":
            evidence = f.get("evidence", "")
            key_match = re.search(r"env key '([^']+)'", evidence)
            if key_match:
                key = key_match.group(1)
                diffs.append(make_diff(
                    rule_id=rule_id,
                    source_url=f.get("source_url", ""),
                    verbatim_quote=f.get("verbatim_quote", ""),
                    location=f.get("location", ""),
                    before=f'"{key}": "<literal-secret>"',
                    after=f'"{key}": "${{{key}}}"',
                    severity=severity,
                    expected_delta=25,
                    voice_drift="low",
                    regression_risk="low",
                    deterministic=True,
                    note=f"Set ${key} env var via shell or secret manager",
                ))

        # AR-CC-082: SSE transport deprecated
        elif rule_id == "AR-CC-082":
            diffs.append(make_diff(
                rule_id=rule_id,
                source_url=f.get("source_url", ""),
                verbatim_quote=f.get("verbatim_quote", ""),
                location=f.get("location", ""),
                before='"transport": "sse"',
                after='"transport": "http"',
                severity=severity,
                expected_delta=8,
                voice_drift="low",
                regression_risk="medium",
                deterministic=True,
                note="Verify server supports HTTP transport before applying",
            ))

        # AR-CC-024: SKILL.md too long
        elif rule_id == "AR-CC-024":
            diffs.append(make_diff(
                rule_id=rule_id,
                source_url=f.get("source_url", ""),
                verbatim_quote=f.get("verbatim_quote", ""),
                location="whole-file",
                before="<body exceeds 500 lines>",
                after="<move detail to references/<topic>.md (1-level deep) and link from SKILL.md>",
                severity=severity,
                expected_delta=15,
                voice_drift="medium",
                regression_risk="medium",
                deterministic=False,
                note="Operator must decide what to extract. See AR-CC-S04 references doctrine.",
            ))

        # AR-CC-002: CLAUDE.md too long
        elif rule_id == "AR-CC-002":
            diffs.append(make_diff(
                rule_id=rule_id,
                source_url=f.get("source_url", ""),
                verbatim_quote=f.get("verbatim_quote", ""),
                location="whole-file",
                before="<file exceeds 200 lines>",
                after="<extract procedural sections to .claude/skills/<name>/ "
                      "and path-conditional rules to .claude/rules/<topic>.md>",
                severity=severity,
                expected_delta=10,
                voice_drift="medium",
                regression_risk="medium",
                deterministic=False,
                note="Operator must apply 'would removing this cause mistakes?' test per line.",
            ))

        # All others: emit Pass 2 template — UNLESS a snippet patch was already
        # emitted for this rule (snippets count as a deterministic fix path).
        else:
            if not applicable_snippets:
                unfixable.append({
                    "rule_id": rule_id,
                    "statement": f.get("statement", ""),
                    "source_url": f.get("source_url", ""),
                    "verbatim_quote": f.get("verbatim_quote", ""),
                    "evidence": f.get("evidence", ""),
                    "location": f.get("location", ""),
                    "severity": severity,
                    "reason": f"detection_method={detection} requires qualitative reasoning. "
                              f"Follow references/pass2-protocol.md § Diff Generation.",
                })

    return diffs, snippet_patches, unfixable


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


def main():
    parser = argparse.ArgumentParser(
        description="Generate surgical diffs and snippet patches for findings"
    )
    parser.add_argument("path", type=Path, help="Artifact path")
    parser.add_argument("--findings", type=Path, required=True,
                        help="findings.json from pass1_mechanical.py")
    parser.add_argument("--type", default=None,
                        help="Artifact type (skill/claude_md/subagent/...) — "
                             "controls snippet type-aware suppression. "
                             "Defaults to value in findings.json if present.")
    parser.add_argument("--apply", action="store_true",
                        help="Write optimized version to <path>.optimized.<ext>")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: {args.path} not found", file=sys.stderr)
        sys.exit(1)
    if not args.findings.exists():
        print(f"Error: {args.findings} not found", file=sys.stderr)
        sys.exit(1)

    content = args.path.read_text(encoding="utf-8", errors="replace")
    fm = extract_frontmatter(content)
    findings_data = json.loads(args.findings.read_text(encoding="utf-8"))
    findings = findings_data.get("findings", []) if isinstance(findings_data, dict) else findings_data

    artifact_type = args.type
    if not artifact_type and isinstance(findings_data, dict):
        artifact_type = findings_data.get("type")

    diffs, snippet_patches, unfixable = generate_diffs(content, findings, fm, artifact_type)

    output = {
        "path": str(args.path),
        "type": artifact_type or "unspecified",
        "rules_version": "1.2",
        "diff_count": len(diffs),
        "snippet_patch_count": len(snippet_patches),
        "unfixable_count": len(unfixable),
        "diffs": diffs,
        "snippet_patches": snippet_patches,
        "unfixable": unfixable,
        "summary": {
            "total_findings": len(findings),
            "deterministic_diffs": sum(1 for d in diffs if d["deterministic"]),
            "template_diffs": sum(1 for d in diffs if not d["deterministic"]),
            "snippet_patches": len(snippet_patches),
            "pass2_required": len(unfixable),
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

    if args.apply:
        # Apply only deterministic diffs (snippet patches require operator
        # decision on insertion location — appended to end as default).
        new_content = content
        applied = 0
        for d in diffs:
            if d["deterministic"] and d["before"] in new_content:
                new_content = new_content.replace(d["before"], d["after"], 1)
                applied += 1
        # Append snippet patches with clear delimiter
        if snippet_patches:
            new_content += "\n\n<!-- ═════ Anthropic-grade snippet patches (verbatim from doc) ═════ -->\n"
            for sp in snippet_patches:
                new_content += f"\n<!-- Snippet: {sp['snippet']} | Source: {sp['source_url']} -->\n"
                new_content += sp["insert_text"] + "\n"
                applied += 1
        out_path = args.path.with_suffix(args.path.suffix + ".optimized")
        out_path.write_text(new_content, encoding="utf-8")
        print(f"\nApplied {applied} patches → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
