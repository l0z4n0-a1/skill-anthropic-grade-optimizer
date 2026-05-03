"""
test_rule_schema.py — schema integrity per rule (189 tests, one per rule_id).

Every rule in references/rules-anthropic.yaml must have:
- unique rule_id
- non-empty verbatim_quote and source_url (Anthropic-grade Law 1: cite or stay silent)
- valid dimension and severity
- detection_method from the allowed set
- applies_to as a non-empty list

These are the contract tests. If any fails, the rule is malformed and Pass-1
or Pass-2 may produce silent false positives or misses.
"""

from collections import Counter
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
RULES_PATH = SKILL_DIR / "references" / "rules-anthropic.yaml"

VALID_DIMENSIONS = {
    "D-CLAR", "D-STRUCT", "D-EXAMPLE", "D-REASON", "D-CONTEXT",
    "D-MODEL", "D-AGENT", "D-EVAL", "D-TOOL", "D-VISION",
    "D-CC", "D-MEMORY", "D-COMMAND", "D-SKILL", "D-SUBAGENT",
    "D-HOOK", "D-MCP", "D-SETTINGS", "D-ARCHITECTURE", "D-SAFETY",
    "D-COMPUTER",
}
VALID_SEVERITIES = {"hard", "critical", "soft", "medium", "high", "low",
                    "warning", "never"}
VALID_DETECTION_METHODS = {"regex", "code-check", "heuristic", "hybrid", "llm-judge"}


def _load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return doc.get("rules", []), doc.get("meta", {})


_RULES, _META = _load_rules()


def test_meta_exists_and_count_matches():
    """meta.total_unique_rules must equal actual rule count (SSOT contract)."""
    assert _META, "rules-anthropic.yaml § meta missing"
    declared = _META.get("total_unique_rules")
    actual = len(_RULES)
    assert declared == actual, (
        f"SSOT drift: meta.total_unique_rules={declared} but actual count={actual}. "
        f"This is the skill's First Law violation — fix one or the other."
    )


def test_rule_ids_are_unique():
    ids = [r.get("rule_id") for r in _RULES]
    counter = Counter(ids)
    dupes = {k: v for k, v in counter.items() if v > 1}
    assert not dupes, f"Duplicate rule_ids: {dupes}"


@pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.get("rule_id", "UNNAMED"))
def test_rule_schema(rule):
    """Each rule must satisfy the contract: id, dimension, severity, method, source, quote, applies_to."""
    rid = rule.get("rule_id")
    assert rid, "rule has no rule_id"
    assert rule.get("dimension") in VALID_DIMENSIONS, \
        f"{rid}: dimension '{rule.get('dimension')}' not in {VALID_DIMENSIONS}"
    assert rule.get("severity") in VALID_SEVERITIES, \
        f"{rid}: severity '{rule.get('severity')}' not in {VALID_SEVERITIES}"
    assert rule.get("detection_method") in VALID_DETECTION_METHODS, \
        f"{rid}: detection_method '{rule.get('detection_method')}' not in {VALID_DETECTION_METHODS}"
    assert rule.get("verbatim_quote", "").strip(), \
        f"{rid}: verbatim_quote empty (Law 1 violation: cite or stay silent)"
    assert rule.get("source_url", "").strip().startswith("http"), \
        f"{rid}: source_url missing or not an http(s) URL"
    applies = rule.get("applies_to") or []
    assert isinstance(applies, list) and applies, \
        f"{rid}: applies_to must be a non-empty list"
    assert rule.get("statement", "").strip(), \
        f"{rid}: statement empty (human-readable summary required)"
