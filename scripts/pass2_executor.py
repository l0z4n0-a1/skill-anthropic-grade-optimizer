#!/usr/bin/env python3
"""
pass2_executor.py — qualitative audit via claude-opus-4-7 with prompt caching.

USAGE:
    python pass2_executor.py <artifact_path> --type <type> [--target opus-4-7]
                              [--max-rules N] [--json-out <path>]

CONTRACT:
    Reads rules-anthropic.yaml § rules where detection_method=llm-judge AND
    artifact's type ∈ rule.applies_to. Sends artifact + applicable rules to
    Claude with the rules block under cache_control (so subsequent calls hit
    cache → ~10x cheaper). Returns structured findings array, identical schema
    to Pass-1, ready to merge into the orchestrator's bundle.

REQUIRES:
    pip install anthropic pyyaml
    ANTHROPIC_API_KEY env var

GRACEFUL DEGRADATION:
    Without anthropic SDK or API key, exits with a structured stub finding
    explaining how to enable Pass-2. Orchestrator can chain unconditionally.
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = SKILL_DIR / "references" / "rules-anthropic.yaml"


PASS2_SYSTEM_PROMPT = """You are the Pass-2 qualitative auditor for the anthropic-grade-optimizer skill.

Your job: read a Claude-directing artifact and judge whether each provided rule
is upheld or violated. You must:

1. Read the artifact carefully.
2. For each rule, decide one of:
   - upheld (artifact follows the rule)
   - violated (artifact contradicts the rule — emit a finding)
   - not_applicable (rule does not apply to this artifact's content)
3. When violated, emit exactly the JSON schema specified below.
4. Cite the rule's verbatim_quote and source_url unchanged.
5. Be precise. Do not invent rules. Do not hallucinate locations.
6. Default to not_applicable when uncertain. False positives are worse than misses.

Output strictly the JSON array described in the user message — no preamble, no markdown fences."""


PASS2_FINDING_SCHEMA = {
    "rule_id": "string — exact rule_id from input",
    "dimension": "string — exact dimension from input",
    "severity": "string — exact severity from input",
    "verdict": "string — 'violated'",
    "location": "string — line range or section reference, e.g. 'lines 42-58' or 'frontmatter.description'",
    "statement": "string — one-line restatement of what was violated",
    "evidence": "string — short quote or paraphrase from the artifact (≤120 chars)",
    "verbatim_quote": "string — copy from input rule, unchanged",
    "source_url": "string — copy from input rule, unchanged",
    "score_impact": "integer — negative; -15 hard, -8 soft, -3 medium, -1 low",
    "triage": "string — '🔴' for hard/critical, '🟡' for soft/medium, '🟢' for low",
    "requires_pass2_grade": False,
}

SEVERITY_TO_IMPACT = {"hard": -15, "critical": -20, "soft": -8, "medium": -5,
                      "high": -8, "low": -2, "warning": -1}
SEVERITY_TO_TRIAGE = {"hard": "🔴", "critical": "🔴", "soft": "🟡", "medium": "🟡",
                      "high": "🟡", "low": "🟢", "warning": "🟢"}


def load_applicable_rules(artifact_type: str, max_rules: int | None = None) -> list:
    """Load llm-judge rules whose applies_to includes the artifact type or 'all'."""
    if yaml is None:
        return []
    with open(RULES_PATH, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    rules = doc.get("rules", [])
    out = []
    for r in rules:
        if r.get("detection_method") != "llm-judge":
            continue
        applies = r.get("applies_to", [])
        if not (artifact_type in applies or "all" in applies):
            continue
        out.append({
            "rule_id": r["rule_id"],
            "dimension": r["dimension"],
            "severity": r.get("severity", "medium"),
            "statement": r.get("statement", ""),
            "verbatim_quote": r.get("verbatim_quote", ""),
            "source_url": r.get("source_url", ""),
        })
    if max_rules:
        out = out[:max_rules]
    return out


def emit_stub(reason: str, artifact_type: str) -> dict:
    """Graceful degradation: return a 'pass-2-not-executed' marker so the orchestrator can proceed."""
    return {
        "executor": "pass2",
        "executed": False,
        "reason": reason,
        "artifact_type": artifact_type,
        "findings": [],
        "rules_evaluated": 0,
        "stub_finding": {
            "rule_id": "PASS2-NOT-EXECUTED",
            "dimension": "META",
            "severity": "low",
            "verdict": "informational",
            "statement": f"Pass-2 qualitative audit not executed: {reason}",
            "score_impact": 0,
            "triage": "🟢",
        },
    }


def execute_pass2(artifact_path: Path, artifact_type: str, target_model: str,
                  max_rules: int | None) -> dict:
    """Run Pass-2 audit via Claude API with prompt caching."""
    try:
        import anthropic
    except ImportError:
        return emit_stub("anthropic SDK not installed (pip install anthropic)", artifact_type)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return emit_stub("ANTHROPIC_API_KEY not set", artifact_type)

    rules = load_applicable_rules(artifact_type, max_rules)
    if not rules:
        return emit_stub(f"no llm-judge rules apply to type '{artifact_type}'", artifact_type)

    artifact_text = artifact_path.read_text(encoding="utf-8", errors="replace")
    rules_block = json.dumps(rules, indent=2, ensure_ascii=False)

    client = anthropic.Anthropic(api_key=api_key)

    # System prompt: stable text first (cacheable), then per-call rules block (cacheable separately).
    # Per Anthropic prompt-caching doctrine: cache_control on the LAST item of the cached prefix.
    system_blocks = [
        {
            "type": "text",
            "text": PASS2_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                "RULES UNDER EVALUATION (each must receive a verdict):\n\n"
                f"{rules_block}\n\n"
                "OUTPUT SCHEMA per finding:\n\n"
                f"{json.dumps(PASS2_FINDING_SCHEMA, indent=2)}\n\n"
                "Emit a JSON array of findings. Empty array if everything is upheld."
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]

    user_message = (
        f"<artifact type=\"{artifact_type}\" path=\"{artifact_path.name}\">\n"
        f"{artifact_text}\n"
        f"</artifact>\n\n"
        f"Evaluate every rule above against this artifact. Return only the JSON array of findings."
    )

    api_model = target_model if target_model.startswith("claude-") else f"claude-{target_model}"

    try:
        response = client.messages.create(
            model=api_model,
            max_tokens=8000,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        return emit_stub(f"API call failed: {type(e).__name__}: {str(e)[:200]}", artifact_type)

    raw = "".join(block.text for block in response.content if hasattr(block, "text"))
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip("` \n")

    try:
        findings_raw = json.loads(raw)
    except json.JSONDecodeError as e:
        return emit_stub(f"model returned non-JSON output: {e}", artifact_type)

    if not isinstance(findings_raw, list):
        return emit_stub("model returned non-array output", artifact_type)

    # Normalize: enforce schema and back-fill score_impact/triage from severity if missing.
    findings = []
    for raw_f in findings_raw:
        if not isinstance(raw_f, dict) or raw_f.get("verdict") != "violated":
            continue
        sev = (raw_f.get("severity") or "medium").lower()
        finding = {
            "finding_id": f"P2-{len(findings) + 1:03d}",
            "rule_id": raw_f.get("rule_id", "?"),
            "dimension": raw_f.get("dimension", "?"),
            "severity": sev,
            "statement": raw_f.get("statement", "")[:200],
            "location": raw_f.get("location", "unknown"),
            "evidence": raw_f.get("evidence", "")[:200],
            "verbatim_quote": raw_f.get("verbatim_quote", ""),
            "source_url": raw_f.get("source_url", ""),
            "score_impact": raw_f.get("score_impact", SEVERITY_TO_IMPACT.get(sev, -3)),
            "triage": raw_f.get("triage", SEVERITY_TO_TRIAGE.get(sev, "🟡")),
            "executor": "pass2",
        }
        findings.append(finding)

    usage = getattr(response, "usage", None)
    cache_info = {}
    if usage:
        cache_info = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        }

    return {
        "executor": "pass2",
        "executed": True,
        "model": api_model,
        "rules_evaluated": len(rules),
        "findings": findings,
        "usage": cache_info,
    }


def main():
    parser = argparse.ArgumentParser(description="Pass-2 qualitative audit via Claude API")
    parser.add_argument("artifact_path", type=Path)
    parser.add_argument("--type", required=True,
                        choices=["claude_md", "skill", "subagent", "slash_command",
                                 "hook_config", "mcp_config", "system_prompt",
                                 "user_prompt", "api_config", "workflow"])
    parser.add_argument("--target", default="claude-opus-4-7")
    parser.add_argument("--max-rules", type=int, default=None,
                        help="Cap rules evaluated per call (cost control)")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    if not args.artifact_path.exists():
        print(json.dumps({"error": f"path not found: {args.artifact_path}"}), file=sys.stderr)
        sys.exit(1)

    result = execute_pass2(args.artifact_path, args.type, args.target, args.max_rules)
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
