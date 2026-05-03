#!/usr/bin/env python3
"""
run_eval_suite.py

USO: python run_eval_suite.py [--save-bundles]
QUANDO USAR: Executar todas as 15 fixtures contra ground-truth e relatar precision/recall.
OUTPUT: Console summary + evals/results/*.report.txt + evals/results/EVAL_MATRIX.md
"""

import io
import json
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


SKILL_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = SKILL_DIR / "evals" / "fixtures"
RESULTS_DIR = SKILL_DIR / "evals" / "results"
GROUND_TRUTH = SKILL_DIR / "evals" / "ground-truth.yaml"


def parse_simple_yaml(text: str) -> dict:
    """Minimal YAML parser for ground-truth.yaml structure."""
    result = {"fixtures": {}}
    current_fixture = None
    current_dict = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        # Detect fixture entry "  fixture-name.md:"
        m_fix = re.match(r"^  ([\w.-]+\.(?:md|json)):", line)
        if m_fix:
            current_fixture = m_fix.group(1)
            result["fixtures"][current_fixture] = {}
            current_dict = result["fixtures"][current_fixture]
            continue
        # Detect inner key
        m_kv = re.match(r"^    (\w+):\s*(.*)", line)
        if m_kv and current_dict is not None:
            key, val = m_kv.group(1), m_kv.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                # parse inline list
                inner = val[1:-1]
                vals = [v.strip() for v in inner.split(",")]
                try:
                    current_dict[key] = [int(v) for v in vals]
                except ValueError:
                    current_dict[key] = vals
            elif val.isdigit():
                current_dict[key] = int(val)
            else:
                current_dict[key] = val.strip('"')
    return result


def run_audit(fixture_path: Path) -> dict:
    """Run skill on fixture, return structured score+findings."""
    cmd = [sys.executable, str(SKILL_DIR / "scripts" / "run.py"),
           str(fixture_path), "--target", "opus-4-7", "--mode", "audit",
           "--json-out", str(RESULTS_DIR / f"{fixture_path.name}.bundle.json")]
    proc = subprocess.run(cmd, capture_output=True)
    stdout = proc.stdout.decode("utf-8", errors="replace")
    bundle_path = RESULTS_DIR / f"{fixture_path.name}.bundle.json"
    if bundle_path.exists():
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    else:
        bundle = {"score": {"score": 0, "grade": "ERROR"},
                  "classification": {"type": "error"},
                  "pass1": {"findings": []}}
    return {
        "stdout": stdout,
        "bundle": bundle,
    }


def grade_letter(grade_str: str) -> str:
    if grade_str.startswith("A"):
        return "A"
    if grade_str.startswith("B"):
        return "B"
    if grade_str.startswith("C"):
        return "C"
    if grade_str.startswith("D"):
        return "D"
    if grade_str.startswith("F--"):
        return "F--"
    if grade_str.startswith("F"):
        return "F"
    return "?"


def evaluate_fixture(fixture_name: str, expected: dict, actual: dict) -> dict:
    score_data = actual["bundle"].get("score", {})
    actual_score = score_data.get("score", 0)
    actual_grade = grade_letter(score_data.get("grade", ""))
    actual_findings = len(actual["bundle"].get("pass1", {}).get("findings", []))
    actual_hard = score_data.get("hard_violations", 0)

    expected_range = expected.get("expected_score_range", [0, 100])
    expected_grade = expected.get("expected_grade", "?")
    expected_count = expected.get("expected_findings_count")
    expected_count_max = expected.get("expected_findings_count_max")
    expected_hard = expected.get("expected_hard")

    in_range = expected_range[0] <= actual_score <= expected_range[1]

    if isinstance(expected_grade, str):
        # Match like "A", "F", "F or F--"
        valid_grades = [g.strip() for g in expected_grade.split("or")]
        grade_match = actual_grade in valid_grades
    else:
        grade_match = False

    findings_match = True
    if expected_count is not None:
        # within ±1 acceptable
        findings_match = abs(actual_findings - expected_count) <= 2
    elif expected_count_max is not None:
        findings_match = actual_findings <= expected_count_max

    hard_match = True
    if expected_hard is not None:
        hard_match = actual_hard == expected_hard

    pass_overall = in_range and grade_match and findings_match

    return {
        "fixture": fixture_name,
        "category": expected.get("category", "?"),
        "actual_score": actual_score,
        "actual_grade": actual_grade,
        "actual_findings": actual_findings,
        "actual_hard": actual_hard,
        "expected_score_range": expected_range,
        "expected_grade": expected_grade,
        "in_range": in_range,
        "grade_match": grade_match,
        "findings_match": findings_match,
        "hard_match": hard_match,
        "pass": pass_overall,
    }


def main():
    if not GROUND_TRUTH.exists():
        print(f"Error: {GROUND_TRUTH} not found", file=sys.stderr)
        sys.exit(1)

    gt = parse_simple_yaml(GROUND_TRUTH.read_text(encoding="utf-8"))
    fixtures_meta = gt.get("fixtures", {})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Anthropic-Grade Optimizer — Eval Matrix")
    print("=" * 80)
    print(f"Total fixtures: {len(fixtures_meta)}")
    print()

    results = []
    for fixture_name, expected in fixtures_meta.items():
        fixture_path = FIXTURES_DIR / fixture_name
        if not fixture_path.exists():
            print(f"  [{fixture_name}] MISSING — skipped")
            continue
        actual = run_audit(fixture_path)
        evaluation = evaluate_fixture(fixture_name, expected, actual)
        results.append(evaluation)
        status = "PASS" if evaluation["pass"] else "FAIL"
        print(f"  [{status:4s}] {fixture_name:38s}  "
              f"score={evaluation['actual_score']:5.1f}/100 "
              f"grade={evaluation['actual_grade']:3s} "
              f"(expected {expected.get('expected_grade', '?'):8s}, "
              f"range {expected.get('expected_score_range', [0, 100])})")

    print()
    print("=" * 80)
    pass_count = sum(1 for r in results if r["pass"])
    print(f"PASS: {pass_count}/{len(results)} fixtures")

    # Per-category breakdown
    by_category = {}
    for r in results:
        cat = r["category"]
        by_category.setdefault(cat, []).append(r)
    for cat, items in sorted(by_category.items()):
        cat_pass = sum(1 for r in items if r["pass"])
        print(f"  {cat:14s}: {cat_pass}/{len(items)}")

    # Save matrix as Markdown
    matrix_path = RESULTS_DIR / "EVAL_MATRIX.md"
    with matrix_path.open("w", encoding="utf-8") as f:
        f.write("# Eval Matrix — Anthropic-Grade Optimizer v1.0\n\n")
        f.write(f"Run date: 2026-05-02 | Pass rate: {pass_count}/{len(results)}\n\n")
        f.write("| Fixture | Category | Score | Grade | Expected | Hard | Findings | PASS |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in results:
            mark = "PASS" if r["pass"] else "FAIL"
            f.write(f"| {r['fixture']} | {r['category']} | {r['actual_score']:.1f} | "
                    f"{r['actual_grade']} | {r['expected_grade']} | "
                    f"{r['actual_hard']} | {r['actual_findings']} | {mark} |\n")
        f.write("\n## Per-Category Pass Rate\n\n")
        for cat, items in sorted(by_category.items()):
            cat_pass = sum(1 for r in items if r["pass"])
            f.write(f"- **{cat}**: {cat_pass}/{len(items)}\n")

    print(f"\nMatrix saved: {matrix_path}")


if __name__ == "__main__":
    main()
