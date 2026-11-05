#!/usr/bin/env python3
"""
run.py — Anthropic-Grade Optimizer Orchestrator

USO: python run.py <artifact_path> [--target opus-4-8] [--mode audit] [--verbose] [--fast] [--push-ceiling]

QUANDO USAR: One-shot entry point for the skill. Chains:
  1. classify_artifact.py
  2. pass1_mechanical.py
  3. score_calculator.py
  4. emits report (concise default)

Pass 2 (qualitative reasoning) is NOT executed by this script — it requires the LLM
to follow references/pass2-protocol.md while reading the artifact. The script emits
a placeholder section in the report indicating which rules require Pass 2 attention.

OUTPUT: stdout report. Optional --json-out <path> for structured artifact.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Local UX layer — pure presentation, no logic.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_ux  # noqa: E402

# Force UTF-8 stdout on Windows so emoji characters render
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def get_skill_dir() -> Path:
    """Return the directory containing this script's parent (the skill root)."""
    env_dir = os.environ.get("CLAUDE_SKILL_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parent.parent


def read_rules_meta(skill_dir: Path) -> dict:
    """SSOT read: rules-anthropic.yaml § meta. Skill's own First Law — never hardcode counts."""
    rules_path = skill_dir / "references" / "rules-anthropic.yaml"
    if yaml is None or not rules_path.exists():
        return {"version": "?", "total_unique_rules": "?", "dissection_date": "?"}
    try:
        with open(rules_path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        meta = doc.get("meta", {}) if isinstance(doc, dict) else {}
        return {
            "version": meta.get("version", "?"),
            "total_unique_rules": meta.get("total_unique_rules", "?"),
            "dissection_date": meta.get("dissection_date", "?"),
        }
    except Exception:
        return {"version": "?", "total_unique_rules": "?", "dissection_date": "?"}


# Operator-declared exceptions: rules with documented justification in SKILL.md § Self-audit.
# Each entry must cite the SKILL.md location where the exception is logged.
DECLARED_EXCEPTIONS = {
    "AR-CC-S14": {
        "reason": "Reserved word 'anthropic' in name is the most precise descriptor of the skill's purpose.",
        "logged_at": "SKILL.md § Self-audit: Open Questions",
        "applies_to_dimension": "D-CC",
    },
}


def run_script(script_path: Path, args: list) -> dict:
    """Run a script and return parsed JSON output."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(script_path)] + args,
        capture_output=True,
        env=env,
    )
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    if result.returncode != 0:
        return {"error": stderr.strip(), "returncode": result.returncode}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": stdout[:500]}


def grade_for(score: float) -> str:
    if score >= 90:
        return "A — Anthropic-grade"
    if score >= 80:
        return "B — Production"
    if score >= 70:
        return "C — Functional"
    if score >= 60:
        return "D — Needs work"
    return "F — Refactor"


def apply_exceptions(findings: list, no_exceptions: bool) -> tuple[list, list]:
    """Split findings into (active, declared_exceptions). When no_exceptions=True, all findings stay active."""
    if no_exceptions:
        return findings, []
    active, exempted = [], []
    for f in findings:
        rule_id = f.get("rule_id", "")
        if rule_id in DECLARED_EXCEPTIONS:
            f_marked = dict(f)
            f_marked["exception"] = DECLARED_EXCEPTIONS[rule_id]
            exempted.append(f_marked)
        else:
            active.append(f)
    return active, exempted


def emit_report(classification: dict, pass1: dict, score_active: dict, score_raw: dict,
                exempted: list, rules_meta: dict, opts: dict,
                pass2_executed: bool = False, pass2: dict | None = None) -> str:
    """Render the audit as a human-first report.

    Plain English by default. --verbose adds rule_ids, severities, technical detail.
    --plain emits only the CI-parseable summary line.
    """
    plain = opts.get("plain", False)
    verbose = opts.get("verbose", False)

    # ── Compute the human-facing data slice ────────────────────────────
    raw_score = score_raw.get("score", 0)
    active_score = score_active.get("score", raw_score)
    findings_all = list(pass1.get("findings", []))
    if pass2 and pass2.get("findings"):
        findings_all.extend(pass2.get("findings", []))
    active_findings = [f for f in findings_all if f.get("rule_id") not in DECLARED_EXCEPTIONS] \
        if not opts['no_exceptions'] else findings_all
    must_fix = [f for f in active_findings if f.get("triage") == "🔴"]
    should_fix = [f for f in active_findings if f.get("triage") == "🟡"]
    may_fix = [f for f in active_findings if f.get("triage") == "🟢"]

    verdict = lib_ux.verdict_for(
        score=active_score,
        hard_violations=score_active.get("hard_violations", 0),
        has_must_fix=len(must_fix) > 0,
    )
    gate_passed = score_active.get("gate_passed", False)
    summary_line = lib_ux.ci_summary_line(
        score=active_score, gate_passed=gate_passed,
        must_fix=len(must_fix), should_fix=len(should_fix), may_fix=len(may_fix),
        exempted=len(exempted),
    )

    # ── --plain short-circuit: emit only the summary line ──────────────
    if plain:
        return summary_line

    lines = []

    # ── 1. Verdict banner — the operator's first second ────────────────
    banner_body = [
        f"{verdict['emoji']}  {verdict['headline']}",
        f"   {verdict['subhead']}",
        "",
        f"   Artifact: {classification.get('path', '?')}",
        f"   Type: {classification.get('type', '?')} · "
        f"{classification.get('line_count', 0)} lines · "
        f"target {opts['target']}",
    ]
    lines.extend(lib_ux.render_box("Audit Result", banner_body))
    lines.append("")

    # ── 2. Score block with bar + percentile anchor ────────────────────
    bar = lib_ux.score_bar(active_score)
    grade = lib_ux.grade_letter(active_score)
    lines.append(f"  Score   {bar}  {active_score:.0f}/100   grade {grade}")
    lines.append(f"          {verdict['percentile']}")
    if exempted:
        raw_bar = lib_ux.score_bar(raw_score)
        lines.append(f"          {raw_bar}  {raw_score:.0f}/100   "
                     f"strict (with --no-exceptions)")
    lines.append("")

    # ── 3. Per-dimension grid ──────────────────────────────────────────
    per_dim = score_active.get("per_dimension", {})
    if per_dim:
        lines.append("  How you scored, by dimension:")
        lines.extend(lib_ux.render_dimensions(per_dim))
        lines.append("")

    # ── 4. Gate status — single visible line ───────────────────────────
    gate_icon = "✓" if gate_passed else "✗"
    gate_label = "GATE PASSED" if gate_passed else "GATE FAILED"
    drift = score_active.get("voice_drift_estimate", 0)
    drift_msg = "voice fully preserved" if drift == 0 else f"voice drift {drift:.0%}"
    lines.append(f"  {gate_icon} {gate_label}  ·  "
                 f"{score_active.get('hard_violations', 0)} critical issues  ·  "
                 f"{drift_msg}")
    lines.append("")

    # ── 5. Findings — what / why / what to do ──────────────────────────
    if must_fix:
        lines.append(lib_ux.render_rule(label="Must fix before shipping"))
        for f in must_fix:
            lines.extend(_render_finding(f, verbose))
            lines.append("")
    if should_fix:
        lines.append(lib_ux.render_rule(label="Should fix for a meaningful lift"))
        for f in should_fix:
            lines.extend(_render_finding(f, verbose))
            lines.append("")
    if may_fix:
        lines.append(lib_ux.render_rule(label="Optional polish"))
        for f in may_fix:
            lines.extend(_render_finding(f, verbose))
            lines.append("")

    # ── 6. Declared exceptions, when present ───────────────────────────
    if exempted:
        lines.append(lib_ux.render_rule(label="Operator-declared exceptions"))
        for f in exempted:
            exc = f.get("exception", {})
            lines.append(f"  • {exc.get('reason', '')[:90]}")
            if verbose:
                lines.append(f"    rule {f.get('rule_id', '?')}, "
                             f"logged at {exc.get('logged_at', '?')}")
        lines.append("  These are intentional. Run with --no-exceptions to see the strict score.")
        lines.append("")

    # ── 7. Pass-2 status — show value even when skipped ────────────────
    if not pass2_executed:
        handoff = (opts.get("pass2_handoff") or {})
        lines.append(lib_ux.render_rule(label="Want a deeper review?"))
        lines.append("  Pass 2 judges qualitative rules that regex cannot —")
        lines.append("  things like \"is this clear?\", \"is the tone consistent?\".")
        if handoff.get("payload_path"):
            payload = handoff["payload_path"]
            findings_path = str(Path(payload).with_suffix(".findings.json"))
            lines.append("")
            lines.append("  Host-native Pass-2 (no API, no key — uses the LLM running this session):")
            lines.append(f"    1. Payload emitted: {payload}")
            lines.append(f"       ({handoff.get('rules_count', '?')} llm-judge rules to evaluate)")
            lines.append(f"    2. Read it, judge each rule, write `violated` findings to:")
            lines.append(f"       {findings_path}")
            lines.append(f"    3. Re-run with: --pass2-findings {findings_path}")
        else:
            lines.append("  Add --pass2 to emit a payload for the host LLM to judge in-context.")
            lines.append("  (No API key required when running inside Claude Code.)")
        lines.append("")

    # ── 8. Coverage caveat — honest, plain English ─────────────────────
    lines.append(lib_ux.render_rule(label="What this audit covered"))
    for ln in lib_ux.coverage_caveat_lines(rules_meta, pass2_executed):
        lines.append(f"  {ln}" if ln else "")
    lines.append("")

    # ── 9. Next step — never an orphan report ──────────────────────────
    next_step = lib_ux.next_step_for(
        verdict, len(must_fix), len(should_fix), len(may_fix), opts['mode']
    )
    lines.append(lib_ux.render_rule(label="Next step"))
    lines.append(f"  → {next_step}")
    lines.append("")

    # ── 10. Edge case: unknown artifact type ───────────────────────────
    if classification.get("type") == "unknown":
        lines.append("  ⚠  We could not detect this artifact's type. "
                     "Pass --type <type> for an accurate audit.")
        lines.append("")

    # ── 11. CI summary line — last line, always parseable ──────────────
    lines.append(summary_line)

    return "\n".join(lines)


def _render_finding(f: dict, verbose: bool) -> list:
    """Render a single finding in plain English. Verbose adds technical detail."""
    enriched = lib_ux.enrich_finding(f)
    out = []
    statement = enriched.get("statement", "").strip() or "Issue detected."
    out.append(f"  {enriched.get('triage', '•')}  {statement}")
    out.append(f"     Why it matters: {enriched['_human_why']}")
    out.append(f"     What to do:     {enriched['_human_what']}")
    if verbose:
        out.append(f"     [{enriched.get('rule_id', '?')} · "
                   f"severity {enriched.get('severity', '?')} · "
                   f"location {enriched.get('location', '?')}]")
        if enriched.get("source_url"):
            out.append(f"     source: {enriched.get('source_url')}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Pass-2 host-emit payload management — collision-free paths + TTL cleanup.
# ──────────────────────────────────────────────────────────────────────────

import tempfile  # local import so module load stays cheap when --pass2 unused

_PAYLOAD_TTL_SECONDS = 3600  # orphan payloads older than 1h are reaped


def _payload_path_for(artifact_path: Path) -> Path:
    """Return a collision-free payload path next to the artifact, or in temp.

    Uses PID + the artifact stem so concurrent audits never overwrite each
    other. Falls back to the system temp dir if the artifact's parent is not
    writable (e.g. read-only deployments).
    """
    name = f".{artifact_path.stem}.{os.getpid()}.pass2-payload.json"
    parent = artifact_path.parent
    if os.access(parent, os.W_OK):
        return parent / name
    return Path(tempfile.gettempdir()) / name


def _cleanup_stale_payloads(directory: Path) -> None:
    """Reap any *.pass2-payload.json (and matching .findings.json) older than TTL.

    Best-effort: silently skips files we can't stat or unlink. Keeps the
    working directory tidy without blowing up the audit on permission errors.
    """
    try:
        now = time.time()
        for p in directory.glob(".*.pass2-payload*.json"):
            try:
                if now - p.stat().st_mtime > _PAYLOAD_TTL_SECONDS:
                    p.unlink()
            except OSError:
                continue
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Anthropic-Grade Optimizer — orchestrator entry point"
    )
    parser.add_argument("path", type=Path, help="Path to artifact file")
    parser.add_argument(
        "--target",
        default="opus-4-8",
        choices=["fable-5", "opus-4-8", "sonnet-5",           # current (matrix v1.2)
                 "opus-4-7", "opus-4-6", "sonnet-4-6",        # legacy profiles
                 "haiku-4-5"],
        help="Target Claude model (default: opus-4-8)",
    )
    parser.add_argument(
        "--mode",
        default="audit",
        choices=["audit", "optimize", "full"],
        help="Operating mode (default: audit)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--fast", action="store_true", help="Top-5 findings only")
    parser.add_argument("--push-ceiling", action="store_true", help="Apply MAY-FIX")
    parser.add_argument("--no-exceptions", action="store_true",
                        help="Disable operator-declared exceptions (strict score)")
    parser.add_argument("--pass2", action="store_true",
                        help="Emit Pass-2 judging payload for the host LLM (no API, no key)")
    parser.add_argument("--pass2-findings", type=Path, default=None,
                        help="Inject host-produced Pass-2 findings JSON and merge into bundle")
    parser.add_argument("--pass2-api", action="store_true",
                        help="LEGACY: use external Anthropic API for Pass-2 (requires SDK + key)")
    parser.add_argument("--pass2-max-rules", type=int, default=None,
                        help="Cap number of llm-judge rules sent to Pass-2 (relevance, not cost)")
    parser.add_argument("--plain", action="store_true",
                        help="Emit only the parseable summary line (for CI/scripts)")
    parser.add_argument("--json-out", type=Path, help="Save full bundle as JSON")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    skill_dir = get_skill_dir()
    scripts_dir = skill_dir / "scripts"

    classification = run_script(scripts_dir / "classify_artifact.py", [str(args.path)])
    if "error" in classification:
        print(f"Classification failed: {classification['error']}", file=sys.stderr)
        sys.exit(2)

    artifact_type = classification.get("type", "unknown")
    if artifact_type == "unknown":
        print("Warning: artifact type unknown. Audit will be incomplete.", file=sys.stderr)

    pass1 = run_script(
        scripts_dir / "pass1_mechanical.py",
        [str(args.path), "--type", artifact_type],
    )
    if "error" in pass1:
        print(f"Pass 1 failed: {pass1['error']}", file=sys.stderr)
        sys.exit(3)

    all_findings = list(pass1.get("findings", []))
    pass2_result = None

    # Inject path: host LLM has already produced findings — merge them now.
    if args.pass2_findings:
        if not args.pass2_findings.exists():
            print(f"Error: --pass2-findings not found: {args.pass2_findings}", file=sys.stderr)
            sys.exit(5)
        p2_args = [str(args.path), "--type", artifact_type, "--inject",
                   "--findings-in", str(args.pass2_findings)]
        pass2_result = run_script(scripts_dir / "pass2_executor.py", p2_args)
        if pass2_result and "findings" in pass2_result:
            all_findings.extend(pass2_result["findings"])

    # Legacy API path: external Anthropic API call (kept for headless/CI).
    elif args.pass2_api:
        p2_args = [str(args.path), "--type", artifact_type, "--api",
                   "--target", f"claude-{args.target}"]
        if args.pass2_max_rules:
            p2_args += ["--max-rules", str(args.pass2_max_rules)]
        pass2_result = run_script(scripts_dir / "pass2_executor.py", p2_args)
        if pass2_result and "findings" in pass2_result:
            all_findings.extend(pass2_result["findings"])

    # Default Pass-2 path: emit a payload for the host LLM to judge in-context.
    elif args.pass2:
        payload_path = _payload_path_for(args.path)
        _cleanup_stale_payloads(payload_path.parent)
        p2_args = [str(args.path), "--type", artifact_type, "--emit",
                   "--emit-out", str(payload_path)]
        if args.pass2_max_rules:
            p2_args += ["--max-rules", str(args.pass2_max_rules)]
        emit_result = run_script(scripts_dir / "pass2_executor.py", p2_args)
        findings_path = payload_path.with_suffix(".findings.json")
        pass2_result = {
            "executor": "pass2",
            "status": "pending_host",
            "executed": False,
            "reason": "payload emitted — awaiting host LLM judging via --pass2-findings",
            "mode": "host-emit",
            "findings": [],
            "rules_evaluated": 0,
            "host_handoff": {
                "payload_path": str(payload_path),
                "findings_path": str(findings_path),
                "rules_count": emit_result.get("rules_count", "?"),
                "next_step": (
                    f"Host LLM: read {payload_path}, judge each rule against "
                    f"`artifact_text`, write `violated` findings as JSON array to "
                    f"{findings_path}, then re-run with --pass2-findings {findings_path}"
                ),
            },
        }

    active_findings, exempted = apply_exceptions(all_findings, args.no_exceptions)

    def score_for(findings_subset: list) -> dict:
        tmp = skill_dir / f"_run_findings.{os.getpid()}.tmp.json"
        tmp.write_text(json.dumps({"findings": findings_subset}), encoding="utf-8")
        try:
            return run_script(scripts_dir / "score_calculator.py", [str(tmp)])
        finally:
            if tmp.exists():
                tmp.unlink()

    score_active = score_for(active_findings)
    score_raw = score_for(all_findings) if exempted else score_active

    if "error" in score_active:
        print(f"Scoring failed: {score_active['error']}", file=sys.stderr)
        sys.exit(4)

    rules_meta = read_rules_meta(skill_dir)
    opts = {"target": args.target, "mode": args.mode, "verbose": args.verbose,
            "no_exceptions": args.no_exceptions, "pass2": args.pass2,
            "plain": args.plain,
            "pass2_handoff": (pass2_result or {}).get("host_handoff")}
    pass2_executed = bool(pass2_result and pass2_result.get("executed"))
    report = emit_report(classification, pass1, score_active, score_raw,
                         exempted, rules_meta, opts, pass2_executed, pass2_result)
    print(report)
    if pass2_result is not None:
        print()
        if pass2_result.get("executed"):
            print(f"PASS 2 — qualitative audit EXECUTED via {pass2_result.get('model', '?')}")
            print(f"  Rules evaluated: {pass2_result.get('rules_evaluated', 0)}")
            print(f"  Findings: {len(pass2_result.get('findings', []))}")
            usage = pass2_result.get("usage", {})
            if usage and usage.get("input_tokens"):
                print(f"  Tokens: in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')} "
                      f"cache_read={usage.get('cache_read_input_tokens', 0)}")
        elif pass2_result.get("mode") == "host-emit":
            handoff = pass2_result.get("host_handoff", {})
            print(f"PASS 2 — payload emitted for host LLM (no API call made)")
            print(f"  Payload: {handoff.get('payload_path', '?')}")
            print(f"  Rules to judge: {handoff.get('rules_count', '?')}")
            print(f"  Next: {handoff.get('next_step', '?')}")
        else:
            print(f"PASS 2 — not executed: {pass2_result.get('reason', 'unknown')}")

    if args.json_out:
        opts_serializable = {k: str(v) if isinstance(v, Path) else v
                              for k, v in vars(args).items()}
        bundle = {
            "classification": classification,
            "pass1": pass1,
            "pass2": pass2_result,
            "score": score_active,            # primary (active) — back-compat alias for downstream tools
            "score_active": score_active,
            "score_raw": score_raw,
            "exempted": exempted,
            "rules_meta": rules_meta,
            "options": opts_serializable,
        }
        args.json_out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"\nJSON bundle saved to: {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
