#!/usr/bin/env python3
"""
score_calculator.py

USO: python score_calculator.py <findings.json>
QUANDO USAR: P5 (VALIDATE) — calcula score agregado a partir de findings.
OUTPUT: JSON {score, grade, per_dimension, voice_drift_estimate, gate_passed}

Score model v1.0 (recalibrated):
- Start at 100
- Each finding's score_impact applied directly to total
- Per-dimension shows where issues cluster (informational, not redistributive)
- Hard violations capped at floor=10 (cannot push to negatives)
- Voice drift estimated from voice-related findings count
"""

import argparse
import io
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


DIMENSION_WEIGHTS = {
    "D-CLAR": 16, "D-STRUCT": 11, "D-EXAMPLE": 8, "D-REASON": 12,
    "D-CONTEXT": 10, "D-MODEL": 10, "D-AGENT": 8, "D-EVAL": 7,
    "D-TOOL": 6, "D-VISION": 4, "D-CC": 8,
}

CC_SUBS = {"D-MEMORY", "D-COMMAND", "D-SUBAGENT", "D-HOOK", "D-MCP",
           "D-SETTINGS", "D-ARCHITECTURE", "D-SKILL", "D-SAFETY"}


def aggregate_dim(dim: str) -> str:
    if dim in CC_SUBS:
        return "D-CC"
    if dim == "D-COMPUTER":
        return "D-VISION"
    return dim


def grade_from_score(score: float) -> str:
    if score >= 90:
        return "A — Anthropic-grade"
    if score >= 80:
        return "B — Production"
    if score >= 70:
        return "C — Functional"
    if score >= 60:
        return "D — Needs work"
    if score >= 40:
        return "F — Refactor"
    return "F-- — Reject"


def calculate(findings: list) -> dict:
    total_penalty = 0.0
    per_dim_penalty = {}
    hard_violations = 0
    voice_drift_signals = 0

    for f in findings:
        dim = f.get("dimension", "D-CLAR")
        agg = aggregate_dim(dim)
        impact = f.get("score_impact", 0)
        # impact is negative; convert to absolute penalty
        penalty = abs(impact) if impact < 0 else 0
        total_penalty += penalty
        per_dim_penalty[agg] = per_dim_penalty.get(agg, 0) + penalty

        sev = f.get("severity", "").lower()
        if sev in ("hard", "critical"):
            hard_violations += 1

        statement = f.get("statement", "").lower()
        if "voice" in statement or "authorial" in statement:
            voice_drift_signals += 1

    # Direct score: 100 - total_penalty, floor 10
    score = max(10.0, round(100.0 - total_penalty, 1))

    # Per-dimension remaining health (informational)
    per_dim_remaining = {}
    for dim in DIMENSION_WEIGHTS:
        penalty_in_dim = per_dim_penalty.get(dim, 0)
        per_dim_remaining[dim] = max(0.0, round(100.0 - penalty_in_dim * 5, 1))

    voice_drift = min(0.30, voice_drift_signals * 0.05)

    return {
        "score": score,
        "grade": grade_from_score(score),
        "per_dimension": per_dim_remaining,
        "per_dimension_penalty": {k: round(v, 1) for k, v in per_dim_penalty.items()},
        "hard_violations": hard_violations,
        "voice_drift_estimate": round(voice_drift, 2),
        "findings_count": len(findings),
        "total_penalty_points": round(total_penalty, 1),
        "gate_passed": (
            hard_violations == 0
            and score >= 70
            and voice_drift <= 0.10
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Calculate aggregate score from findings")
    parser.add_argument("findings_path", type=Path)
    args = parser.parse_args()

    if not args.findings_path.exists():
        print(json.dumps({"error": f"path not found: {args.findings_path}"}), file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.findings_path.read_text(encoding="utf-8"))
    findings = data.get("findings", []) if isinstance(data, dict) else data

    result = calculate(findings)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
