#!/usr/bin/env python3
"""
pass2_executor.py — qualitative audit via the host LLM (Claude Code session).

DEFAULT MODE — emit/inject (host-native, no API, no key):
    Phase 1 (emit):
        python pass2_executor.py <artifact_path> --type <type> --emit \\
                                  --emit-out <payload.json>
    → Writes a self-contained judging payload (artifact + rules + schema +
      system instructions). The host LLM reads it, performs the qualitative
      verdicts in-context, and writes findings to <findings.json>.

    Phase 2 (inject):
        python pass2_executor.py <artifact_path> --type <type> --inject \\
                                  --findings-in <findings.json>
    → Validates and normalizes the host-produced findings into the canonical
      Pass-2 bundle schema, ready for merge by run.py.

LEGACY MODE — --api (external API call):
    Retained for headless/CI environments where no host LLM is present.
    Requires `pip install anthropic` and ANTHROPIC_API_KEY. Deprecated for
    interactive use: prefer emit/inject when running inside Claude Code.

CONTRACT:
    Reads rules-anthropic.yaml § rules where detection_method=llm-judge AND
    artifact's type ∈ rule.applies_to. Returns structured findings array,
    identical schema to Pass-1, ready to merge into the orchestrator bundle.
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


# Status enum — single source of truth for Pass-2 lifecycle state.
# `executed: bool` is preserved as a back-compat alias (True iff status == "executed").
STATUS_EXECUTED = "executed"           # findings produced and ready to merge
STATUS_PENDING_HOST = "pending_host"   # payload emitted, awaiting host LLM judging + inject
STATUS_FAILED = "failed"               # API/SDK/key/network/etc — not the host's fault
STATUS_NO_RULES = "no_rules"           # no llm-judge rules apply to this artifact type


def emit_stub(reason: str, artifact_type: str,
              status: str = STATUS_FAILED) -> dict:
    """Graceful degradation: return a structured marker so the orchestrator can proceed.

    `status` distinguishes failure modes; `executed` is the legacy bool alias.
    `reason` is ALWAYS populated — consumers (and tests) can rely on its presence.
    """
    return {
        "executor": "pass2",
        "status": status,
        "executed": status == STATUS_EXECUTED,
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


def emit_payload(artifact_path: Path, artifact_type: str, max_rules: int | None) -> dict:
    """Phase 1 of host-native Pass-2: build a self-contained judging payload.

    The host LLM (Claude Code session) reads this payload, evaluates each rule
    against the artifact text, and writes findings to a sibling JSON file.
    No API call, no key, no external dependency.
    """
    rules = load_applicable_rules(artifact_type, max_rules)
    if not rules:
        return emit_stub(
            f"no llm-judge rules apply to type '{artifact_type}'",
            artifact_type, status=STATUS_NO_RULES,
        )
    artifact_text = artifact_path.read_text(encoding="utf-8", errors="replace")
    return {
        "executor": "pass2",
        "status": STATUS_PENDING_HOST,
        "executed": False,
        "reason": "payload emitted — awaiting host LLM judging via --inject",
        "mode": "emit",
        "artifact_path": str(artifact_path),
        "artifact_type": artifact_type,
        "artifact_text": artifact_text,
        "rules": rules,
        "rules_count": len(rules),
        "system_prompt": PASS2_SYSTEM_PROMPT,
        "finding_schema": PASS2_FINDING_SCHEMA,
        "instructions_for_host": (
            "You are the host LLM running inside Claude Code. The skill needs you "
            "to perform Pass-2 qualitative judging natively (no API call). "
            "For each rule in `rules`, decide upheld | violated | not_applicable "
            "against `artifact_text`. Emit only `violated` findings as a JSON array "
            "matching `finding_schema`, then write the array to the path indicated "
            "by --inject in the next invocation. Default to not_applicable when "
            "uncertain (false positives are worse than misses)."
        ),
    }


def normalize_host_findings(raw_findings: list, artifact_type: str) -> dict:
    """Phase 2 of host-native Pass-2: validate and normalize host-produced findings."""
    if not isinstance(raw_findings, list):
        return emit_stub("host findings file is not a JSON array", artifact_type)

    findings = []
    for raw_f in raw_findings:
        if not isinstance(raw_f, dict):
            continue
        verdict = raw_f.get("verdict", "violated")
        if verdict not in ("violated", None):
            continue
        sev = (raw_f.get("severity") or "medium").lower()
        finding = {
            "finding_id": f"P2-{len(findings) + 1:03d}",
            "rule_id": raw_f.get("rule_id", "?"),
            "dimension": raw_f.get("dimension", "?"),
            "severity": sev,
            "statement": str(raw_f.get("statement", ""))[:200],
            "location": raw_f.get("location", "unknown"),
            "evidence": str(raw_f.get("evidence", ""))[:200],
            "verbatim_quote": raw_f.get("verbatim_quote", ""),
            "source_url": raw_f.get("source_url", ""),
            "score_impact": raw_f.get("score_impact", SEVERITY_TO_IMPACT.get(sev, -3)),
            "triage": raw_f.get("triage", SEVERITY_TO_TRIAGE.get(sev, "🟡")),
            "executor": "pass2-host",
        }
        findings.append(finding)

    return {
        "executor": "pass2",
        "status": STATUS_EXECUTED,
        "executed": True,
        "reason": "host LLM produced findings; normalized into Pass-2 schema",
        "mode": "host-native",
        "model": "host-llm (Claude Code session)",
        "rules_evaluated": len(raw_findings),
        "findings": findings,
        "usage": {"input_tokens": 0, "output_tokens": 0,
                  "note": "host-native execution; tokens accounted in parent session"},
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
        "status": STATUS_EXECUTED,
        "executed": True,
        "reason": f"Pass-2 audited {len(rules)} rules via {api_model}",
        "mode": "api",
        "model": api_model,
        "rules_evaluated": len(rules),
        "findings": findings,
        "usage": cache_info,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Pass-2 qualitative audit. Default: host-native emit/inject (no API)."
    )
    parser.add_argument("artifact_path", type=Path)
    parser.add_argument("--type", required=True,
                        choices=["claude_md", "skill", "subagent", "slash_command",
                                 "hook_config", "mcp_config", "system_prompt",
                                 "user_prompt", "api_config", "workflow"])
    parser.add_argument("--target", default="claude-opus-4-7",
                        help="Target model label (informational; host LLM does the judging)")
    parser.add_argument("--max-rules", type=int, default=None,
                        help="Cap rules evaluated (relevance, not cost — host LLM is free)")
    parser.add_argument("--json-out", type=Path, default=None)

    # Mode selection (mutually exclusive). Default: --emit.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--emit", action="store_true",
                      help="Phase 1: emit judging payload for the host LLM (default)")
    mode.add_argument("--inject", action="store_true",
                      help="Phase 2: normalize host-produced findings into Pass-2 bundle")
    mode.add_argument("--api", action="store_true",
                      help="LEGACY: call external Anthropic API (requires SDK + key)")

    parser.add_argument("--emit-out", type=Path, default=None,
                        help="With --emit: where to write the judging payload (default: stdout)")
    parser.add_argument("--findings-in", type=Path, default=None,
                        help="With --inject: path to host-produced findings JSON array")

    args = parser.parse_args()

    if not args.artifact_path.exists():
        print(json.dumps({"error": f"path not found: {args.artifact_path}"}), file=sys.stderr)
        sys.exit(1)

    # Default behavior when no mode flag: emit (host-native).
    if not (args.emit or args.inject or args.api):
        args.emit = True

    if args.inject:
        if not args.findings_in or not args.findings_in.exists():
            print(json.dumps({"error": "--inject requires --findings-in <path>"}), file=sys.stderr)
            sys.exit(1)
        try:
            raw = json.loads(args.findings_in.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"findings file invalid JSON: {e}"}), file=sys.stderr)
            sys.exit(1)
        result = normalize_host_findings(raw, args.type)
    elif args.api:
        result = execute_pass2(args.artifact_path, args.type, args.target, args.max_rules)
    else:  # --emit (default)
        result = emit_payload(args.artifact_path, args.type, args.max_rules)

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    out_path = args.emit_out if (args.emit and args.emit_out) else args.json_out
    if out_path:
        out_path.write_text(payload, encoding="utf-8")
        print(json.dumps({"written": str(out_path), "mode": result.get("mode", "?"),
                          "rules_count": result.get("rules_count", len(result.get("findings", [])))},
                         indent=2))
    else:
        print(payload)


if __name__ == "__main__":
    main()
