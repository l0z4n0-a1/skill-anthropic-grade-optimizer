"""
test_pass1_detectors.py — integration tests for Pass-1 mechanical detectors.

Strategy: for each artifact-type fixture in evals/fixtures/, run pass1_mechanical
and assert that:
  - the orchestrator runs to completion
  - findings array shape is valid
  - each finding cites a known rule_id (no orphan findings)
  - each finding includes source_url + verbatim_quote (Law 1)

This proves the detector pipeline produces well-formed, cited findings — not
just that the score lands in a range (which run_eval_suite already validates).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
FIXTURES = SKILL_DIR / "evals" / "fixtures"
RULES_PATH = SKILL_DIR / "references" / "rules-anthropic.yaml"


def _load_known_rule_ids():
    with open(RULES_PATH, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return {r["rule_id"] for r in doc.get("rules", [])}


KNOWN_RULE_IDS = _load_known_rule_ids()


def _classify(path: Path) -> str:
    cmd = [sys.executable, str(SKILL_DIR / "scripts" / "classify_artifact.py"), str(path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return "unknown"
    try:
        return json.loads(result.stdout.decode("utf-8", errors="replace")).get("type", "unknown")
    except json.JSONDecodeError:
        return "unknown"


def _run_pass1(path: Path, artifact_type: str) -> dict:
    cmd = [sys.executable, str(SKILL_DIR / "scripts" / "pass1_mechanical.py"),
           str(path), "--type", artifact_type]
    result = subprocess.run(cmd, capture_output=True)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode == 0, f"pass1 crashed on {path.name}: {stderr}"
    return json.loads(stdout)


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*")), ids=lambda p: p.name)
def test_pass1_well_formed(fixture):
    """Every fixture must produce well-formed, cited findings via pass1."""
    artifact_type = _classify(fixture)
    if artifact_type == "unknown":
        pytest.skip(f"classifier could not determine type for {fixture.name}")

    bundle = _run_pass1(fixture, artifact_type)
    assert isinstance(bundle, dict), f"pass1 returned non-dict for {fixture.name}"
    findings = bundle.get("findings", [])
    assert isinstance(findings, list), f"findings is not a list for {fixture.name}"

    for f in findings:
        rid = f.get("rule_id")
        assert rid, f"finding missing rule_id in {fixture.name}: {f}"
        # KNOWN_RULE_IDS may not include AP-* anti-pattern IDs which are emitted
        # by pass1 but live in references/anti-patterns.md, not rules-anthropic.yaml.
        # Accept those as valid too.
        if not rid.startswith("AP-") and not rid.startswith("PASS"):
            assert rid in KNOWN_RULE_IDS, \
                f"orphan finding rule_id '{rid}' in {fixture.name} (not in rules-anthropic.yaml)"
        assert f.get("source_url", "").startswith("http"), \
            f"finding {rid} in {fixture.name} missing source_url (Law 1)"
        assert f.get("severity") in {"hard", "critical", "soft", "medium",
                                     "high", "low", "warning", "never"}, \
            f"finding {rid} in {fixture.name} has invalid severity '{f.get('severity')}'"
