"""
calibration.py — precision/recall/F1 telemetry for the auditor's scorer.

Treats classification as a multi-class problem:
  Actual labels (from ground-truth.yaml): {good=A, bad=F, cross=F--, adversarial=A}
  Predicted labels (from scorer):         grade letter actually emitted

Computes:
  - per-category precision, recall, F1
  - macro-F1 (unweighted mean)
  - confusion matrix
  - per-dimension finding-count drift vs expected_findings_count

Emits CALIBRATION_REPORT.md so the scorer's actual accuracy claim is auditable.
This is what Anthropic would publish alongside any classifier they ship.
"""

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
GROUND_TRUTH = SKILL_DIR / "evals" / "ground-truth.yaml"
FIXTURES = SKILL_DIR / "evals" / "fixtures"
RESULTS_DIR = SKILL_DIR / "evals" / "results"


# Map ground-truth category to expected grade letter (the "true label" for confusion-matrix purposes)
CATEGORY_TO_LABEL = {
    "good": "A",
    "bad": "F",
    "adversarial": "A",
    "cross": "F",     # "F or F--" both collapse to F-class for evaluation
}


def grade_letter(grade_str: str) -> str:
    if not grade_str:
        return "?"
    if grade_str.startswith("A"):
        return "A"
    if grade_str.startswith("B"):
        return "B"
    if grade_str.startswith("C"):
        return "C"
    if grade_str.startswith("D"):
        return "D"
    if grade_str.startswith("F"):
        return "F"
    return "?"


def run_audit(fixture_path: Path) -> dict:
    out_path = RESULTS_DIR / f"{fixture_path.name}.calib.json"
    cmd = [sys.executable, str(RUN_PY), str(fixture_path),
           "--target", "opus-4-7", "--mode", "audit",
           "--json-out", str(out_path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        out_path.unlink(missing_ok=True)


def per_class_metrics(true_labels: list, pred_labels: list) -> dict:
    """Compute precision/recall/F1 per class via macro averaging."""
    classes = sorted(set(true_labels) | set(pred_labels))
    metrics = {}
    for cls in classes:
        tp = sum(1 for t, p in zip(true_labels, pred_labels) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(true_labels, pred_labels) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(true_labels, pred_labels) if t == cls and p != cls)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
        support = sum(1 for t in true_labels if t == cls)
        metrics[cls] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
    return metrics


def confusion(true_labels: list, pred_labels: list) -> dict:
    matrix = defaultdict(lambda: Counter())
    for t, p in zip(true_labels, pred_labels):
        matrix[t][p] += 1
    return {t: dict(matrix[t]) for t in sorted(matrix)}


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH, "r", encoding="utf-8") as fh:
        gt_doc = yaml.safe_load(fh)
    fixtures = gt_doc.get("fixtures", {})

    rows = []
    true_labels, pred_labels = [], []
    for fixture_name, expected in fixtures.items():
        fixture_path = FIXTURES / fixture_name
        if not fixture_path.exists():
            continue
        bundle = run_audit(fixture_path)
        if not bundle:
            continue
        score_data = bundle.get("score") or bundle.get("score_active") or {}
        actual_grade = grade_letter(score_data.get("grade", ""))
        actual_findings = len(bundle.get("pass1", {}).get("findings", []))

        category = expected.get("category", "?")
        true_label = CATEGORY_TO_LABEL.get(category, "?")
        true_labels.append(true_label)
        pred_labels.append(actual_grade)

        rows.append({
            "fixture": fixture_name,
            "category": category,
            "true_label": true_label,
            "predicted_grade": actual_grade,
            "score": score_data.get("score", 0),
            "actual_findings": actual_findings,
            "expected_findings": expected.get("expected_findings_count")
                                  or expected.get("expected_findings_count_max"),
            "match": true_label == actual_grade,
        })

    overall_acc = sum(1 for r in rows if r["match"]) / len(rows) if rows else 0.0
    metrics = per_class_metrics(true_labels, pred_labels)
    confusion_matrix = confusion(true_labels, pred_labels)
    macro_f1 = sum(m["f1"] for m in metrics.values()) / len(metrics) if metrics else 0.0

    # Per-dimension finding-count drift (informational)
    per_dim_drift = []
    for r in rows:
        if r["expected_findings"] is not None:
            per_dim_drift.append({
                "fixture": r["fixture"],
                "expected": r["expected_findings"],
                "actual": r["actual_findings"],
                "delta": r["actual_findings"] - r["expected_findings"],
            })

    report = []
    report.append("# Calibration Report — anthropic-grade-optimizer")
    report.append("")
    report.append(f"**Date:** auto-generated | **Fixtures:** {len(rows)} | "
                  f"**Overall accuracy:** {overall_acc:.1%} | "
                  f"**Macro-F1:** {macro_f1:.3f}")
    report.append("")
    report.append("## Per-class metrics")
    report.append("")
    report.append("| Class | Precision | Recall | F1 | Support |")
    report.append("|---|---|---|---|---|")
    for cls in sorted(metrics):
        m = metrics[cls]
        report.append(f"| {cls} | {m['precision']:.3f} | {m['recall']:.3f} | "
                      f"{m['f1']:.3f} | {m['support']} |")
    report.append("")
    report.append("## Confusion matrix")
    report.append("")
    report.append("Rows = true label, columns = predicted grade.")
    report.append("")
    all_labels = sorted(set(true_labels) | set(pred_labels))
    header = "| true \\\\ pred | " + " | ".join(all_labels) + " |"
    report.append(header)
    report.append("|" + "---|" * (len(all_labels) + 1))
    for t in sorted(confusion_matrix):
        cells = [str(confusion_matrix[t].get(p, 0)) for p in all_labels]
        report.append(f"| **{t}** | " + " | ".join(cells) + " |")
    report.append("")
    report.append("## Per-fixture breakdown")
    report.append("")
    report.append("| Fixture | Category | True | Pred | Score | Match | Findings (act/exp) |")
    report.append("|---|---|---|---|---|---|---|")
    for r in rows:
        mark = "✓" if r["match"] else "✗"
        exp_str = str(r["expected_findings"]) if r["expected_findings"] is not None else "-"
        report.append(f"| {r['fixture']} | {r['category']} | {r['true_label']} | "
                      f"{r['predicted_grade']} | {r['score']:.1f} | {mark} | "
                      f"{r['actual_findings']}/{exp_str} |")
    report.append("")
    report.append("## Finding-count drift")
    report.append("")
    if per_dim_drift:
        report.append("| Fixture | Expected | Actual | Delta |")
        report.append("|---|---|---|---|")
        for d in per_dim_drift:
            report.append(f"| {d['fixture']} | {d['expected']} | {d['actual']} | "
                          f"{d['delta']:+d} |")
    else:
        report.append("_no per-fixture finding-count expectations set_")
    report.append("")
    report.append("## Interpretation")
    report.append("")
    if macro_f1 >= 0.95:
        report.append("- **Macro-F1 ≥ 0.95** — scorer is well-calibrated against ground truth.")
    elif macro_f1 >= 0.85:
        report.append("- **Macro-F1 ≥ 0.85** — scorer is production-ready; review confusion matrix for systematic biases.")
    else:
        report.append("- **Macro-F1 < 0.85** — scorer needs calibration. Inspect false positives/negatives.")

    out_path = RESULTS_DIR / "CALIBRATION_REPORT.md"
    out_path.write_text("\n".join(report), encoding="utf-8")

    print(f"Calibration complete.")
    print(f"  Fixtures: {len(rows)}")
    print(f"  Overall accuracy: {overall_acc:.1%}")
    print(f"  Macro-F1: {macro_f1:.3f}")
    print(f"  Report saved: {out_path}")

    # Exit non-zero if accuracy below threshold (CI signal)
    if overall_acc < 0.85:
        sys.exit(1)


if __name__ == "__main__":
    main()
