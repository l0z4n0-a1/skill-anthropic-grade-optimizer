"""
test_orchestrator.py — end-to-end orchestrator contract tests.

Verifies:
  - bundle JSON contains all promised keys (score, score_active, score_raw,
    pass1, pass2, exempted, rules_meta, classification, options)
  - back-compat alias 'score' equals score_active
  - rules_meta.total_unique_rules matches the SSOT in rules-anthropic.yaml
  - --no-exceptions flips exception application
  - --pass2 invokes the executor (degrades gracefully without API key)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
SELF_SKILL = SKILL_DIR / "SKILL.md"


def _run(args: list[str]) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
        out_path = Path(tmp.name)
    try:
        cmd = [sys.executable, str(RUN_PY), *args, "--json-out", str(out_path)]
        result = subprocess.run(cmd, capture_output=True)
        stderr = result.stderr.decode("utf-8", errors="replace")
        assert result.returncode == 0, f"run.py exited {result.returncode}: {stderr}"
        return json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        out_path.unlink(missing_ok=True)


def test_bundle_has_required_keys():
    bundle = _run([str(SELF_SKILL), "--target", "opus-4-7", "--mode", "audit"])
    for key in ["classification", "pass1", "score", "score_active",
                "score_raw", "exempted", "rules_meta", "options"]:
        assert key in bundle, f"bundle missing required key '{key}'"


def test_score_alias_matches_active():
    bundle = _run([str(SELF_SKILL), "--target", "opus-4-7"])
    assert bundle["score"] == bundle["score_active"], \
        "back-compat alias 'score' must equal 'score_active'"


def test_rules_meta_matches_ssot():
    bundle = _run([str(SELF_SKILL), "--target", "opus-4-7"])
    with open(SKILL_DIR / "references" / "rules-anthropic.yaml", "r", encoding="utf-8") as fh:
        ssot = yaml.safe_load(fh)["meta"]
    assert bundle["rules_meta"]["total_unique_rules"] == ssot["total_unique_rules"]
    assert bundle["rules_meta"]["version"] == ssot["version"]


def test_no_exceptions_flag_changes_score():
    """--no-exceptions must yield a score ≤ active score (never higher)."""
    active = _run([str(SELF_SKILL), "--target", "opus-4-7"])
    strict = _run([str(SELF_SKILL), "--target", "opus-4-7", "--no-exceptions"])
    assert strict["score_active"]["score"] <= active["score_active"]["score"], \
        "strict score must be ≤ active score"


def test_pass2_flag_invokes_executor():
    """--pass2 must populate bundle['pass2'] with a tri-state status and non-empty reason.

    Valid states after --pass2 (default = host-emit path):
      - status == 'executed'      → findings produced (host-inject path)
      - status == 'pending_host'  → payload emitted, awaiting host LLM judging
      - status == 'no_rules'      → artifact type has no llm-judge rules
      - status == 'failed'        → API/SDK/key/network error (legacy --pass2-api path)

    Every non-executed state MUST carry a non-empty `reason`.
    `executed` (legacy bool) MUST be True iff status == 'executed'.
    """
    bundle = _run([str(SELF_SKILL), "--target", "opus-4-7", "--pass2"])
    assert bundle.get("pass2") is not None, "pass2 result should be present when --pass2 is set"
    pass2 = bundle["pass2"]

    valid_status = {"executed", "pending_host", "no_rules", "failed"}
    status = pass2.get("status")
    assert status in valid_status, f"status must be one of {valid_status}; got {status!r}"

    # Legacy bool alias must agree with the enum.
    assert pass2["executed"] is (status == "executed"), \
        "`executed` bool must mirror `status == 'executed'`"

    # Every state ships a reason. Non-executed states MUST explain themselves.
    reason = pass2.get("reason", "")
    assert reason, f"pass2.reason must always be populated; got {reason!r}"

    if status == "pending_host":
        # Host-emit contract: payload + findings paths must be reachable.
        handoff = pass2.get("host_handoff", {})
        assert handoff.get("payload_path"), "pending_host must expose payload_path"
        assert handoff.get("findings_path"), "pending_host must expose findings_path"
    elif status == "failed":
        # Legacy degradation path (only reachable via --pass2-api).
        assert ("ANTHROPIC_API_KEY" in reason) or ("anthropic" in reason.lower()), \
            f"failed state must reference SDK or API key; got: {reason!r}"


def test_pass2_omitted_by_default():
    bundle = _run([str(SELF_SKILL), "--target", "opus-4-7"])
    assert bundle.get("pass2") is None, "pass2 must be None when --pass2 is not set"
