#!/usr/bin/env python3
"""
classify_artifact.py

USO: python classify_artifact.py <path>
QUANDO USAR: P1 (CLASSIFY) — detecta tipo do artefato e sinaliza características.
OUTPUT: JSON em stdout com {type, line_count, char_count, language, has_frontmatter, signals}
"""

import argparse
import json
import re
import sys
from pathlib import Path


CANONICAL_TYPES = [
    "claude_md",
    "skill",
    "slash_command",
    "subagent",
    "hook_config",
    "mcp_config",
    "system_prompt",
    "user_prompt",
    "workflow",
    "unknown",
]


def detect_language(content: str) -> str:
    pt_markers = re.findall(r"\b(você|para|com|que|não|sim|qual|quando|porque)\b", content, re.IGNORECASE)
    en_markers = re.findall(r"\b(you|the|with|that|not|when|because|which)\b", content, re.IGNORECASE)
    return "pt" if len(pt_markers) > len(en_markers) else "en"


def has_yaml_frontmatter(content: str) -> bool:
    return content.lstrip().startswith("---\n") and "\n---\n" in content[:2000]


def extract_frontmatter(content: str) -> dict:
    if not has_yaml_frontmatter(content):
        return {}
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return {}
    fm_text = parts[1]
    fm = {}
    for line in fm_text.splitlines():
        m = re.match(r"^([a-z][a-z0-9_-]*)\s*:\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def classify(path: Path, content: str) -> dict:
    name = path.name.lower()
    parent = path.parent.name.lower() if path.parent else ""
    grandparent = path.parent.parent.name.lower() if path.parent and path.parent.parent else ""

    fm = extract_frontmatter(content)
    has_fm = bool(fm)

    # CLAUDE.md detection (filename match — case-insensitive, also matches bad-claude-md)
    if name in ("claude.md", "claude.local.md") or "claude-md" in name or "claude_md" in name:
        artifact_type = "claude_md"
    # SKILL.md detection (filename or frontmatter+context)
    elif name == "skill.md":
        artifact_type = "skill"
    elif name.endswith(".md") and has_fm and "name" in fm and "description" in fm:
        # frontmatter pattern matches skill spec
        if "subagent" in name or "agent" in name:
            artifact_type = "subagent"
        else:
            artifact_type = "skill"
    # Subagent (folder OR filename hint OR frontmatter description-only without name)
    elif name.endswith(".md") and ("agent" in name or parent == "agents"):
        artifact_type = "subagent"
    # Slash command (legacy)
    elif parent == "commands" and name.endswith(".md"):
        artifact_type = "slash_command"
    # Hook config (settings.json with hooks key)
    elif name in ("settings.json", "settings.local.json") or "hook" in name:
        try:
            data = json.loads(content)
            if "hooks" in data:
                artifact_type = "hook_config"
            else:
                artifact_type = "unknown"
        except Exception:
            artifact_type = "unknown"
    # MCP config (filename match)
    elif name in (".mcp.json", "mcp.json", ".claude.json") or "mcp" in name:
        try:
            data = json.loads(content)
            if "mcpServers" in data or "mcp_servers" in data:
                artifact_type = "mcp_config"
            else:
                artifact_type = "unknown"
        except Exception:
            artifact_type = "unknown"
    # Workflow
    elif name.endswith((".yaml", ".yml")) and "workflow" in (name + parent):
        artifact_type = "workflow"
    # CLAUDE.md by content heuristic — top-level memory file pattern
    elif name.endswith(".md") and re.search(r"^# CLAUDE\.md", content, re.MULTILINE | re.IGNORECASE):
        artifact_type = "claude_md"
    # Default heuristic on .md
    elif name.endswith(".md"):
        artifact_type = "system_prompt"  # generic prompt artifact
    else:
        artifact_type = "unknown"

    line_count = content.count("\n") + 1
    char_count = len(content)
    language = detect_language(content)

    signals = {
        "has_xml_tags": bool(re.search(r"<[a-z_]+>", content)),
        "has_examples_blocks": bool(re.search(r"<example>", content)),
        "has_all_caps_imperatives": bool(re.findall(r"\b[A-Z]{4,}\b", content)),
        "has_critical_must": bool(re.search(r"\bCRITICAL\b|\bYOU MUST\b|\bIMPORTANT\b", content)),
        "has_relative_paths": bool(re.search(r'(?<![\\/])\./', content)) or bool(re.search(r"\\\\", content)),
        "has_backslash_paths": bool(re.search(r"[A-Z]:\\", content)),
        "frontmatter_keys": list(fm.keys()) if fm else [],
    }

    return {
        "path": str(path),
        "type": artifact_type,
        "line_count": line_count,
        "char_count": char_count,
        "language": language,
        "has_frontmatter": has_fm,
        "frontmatter": fm,
        "signals": signals,
    }


def main():
    parser = argparse.ArgumentParser(description="Classify Claude-directing artifact for audit.")
    parser.add_argument("path", type=Path, help="Path to artifact file")
    args = parser.parse_args()

    if not args.path.exists():
        print(json.dumps({"error": f"path not found: {args.path}"}), file=sys.stderr)
        sys.exit(1)

    content = args.path.read_text(encoding="utf-8", errors="replace")
    result = classify(args.path, content)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
