#!/usr/bin/env python3
"""
check_model_currency.py — fails CI when modulation-matrix.yaml drifts from known-current Anthropic models.

USAGE:
    python check_model_currency.py [--update-known]

CONTRACT:
    KNOWN_CURRENT_MODELS is the SSOT for "what Anthropic ships today".
    Bump it explicitly when a new model lands. Never auto-pull at runtime —
    that would let upstream changes silently invalidate audits in flight.

EXIT CODES:
    0 — modulation-matrix.yaml covers every known-current model
    1 — drift detected (missing profile, missing api_id, or stale 'current' set)
    2 — modulation-matrix.yaml not parseable
"""

import argparse
import io
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. pip install pyyaml", file=sys.stderr)
    sys.exit(2)

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# SSOT for "what Anthropic ships as of the dissection date in rules-anthropic.yaml".
# When Anthropic releases a new model, bump this set + add a profile to modulation-matrix.yaml
# in the same PR. CI will fail until both are updated together.
KNOWN_CURRENT_MODELS = {
    "claude-fable-5": {"profile_key": "fable-5", "released": "2026-06-09"},
    "claude-opus-4-8": {"profile_key": "opus-4-8", "released": "2026-H1"},
    "claude-sonnet-5": {"profile_key": "sonnet-5", "released": "2026-H1"},
    "claude-haiku-4-5-20251001": {"profile_key": "haiku-4-5", "released": "2025-10-15"},
}

# Profiles kept in modulation-matrix.yaml for legacy models (still available per
# platform.claude.com/docs/en/about-claude/models/overview "Legacy models", 2026-07-11).
# Not flagged as stale by the reverse check; never delete their matrix cells.
KNOWN_LEGACY_PROFILE_KEYS = {"opus-4-7", "opus-4-6", "sonnet-4-6"}

SKILL_DIR = Path(__file__).resolve().parent.parent
MATRIX_PATH = SKILL_DIR / "references" / "modulation-matrix.yaml"


def load_matrix() -> dict:
    if not MATRIX_PATH.exists():
        print(f"FAIL: {MATRIX_PATH} not found", file=sys.stderr)
        sys.exit(2)
    try:
        with open(MATRIX_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as e:
        print(f"FAIL: cannot parse {MATRIX_PATH}: {e}", file=sys.stderr)
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.parse_args()

    matrix = load_matrix()
    drift = []

    for api_id, info in KNOWN_CURRENT_MODELS.items():
        profile_key = info["profile_key"]
        profile = matrix.get(profile_key)
        if profile is None:
            drift.append(f"MISSING PROFILE: {api_id} (expected key '{profile_key}')")
            continue
        declared_api_id = profile.get("api_id") or profile.get("api_alias")
        if declared_api_id != api_id and api_id != profile.get("api_alias"):
            # Allow alias match (haiku-4-5 case)
            aliases = {profile.get("api_id"), profile.get("api_alias")}
            if api_id not in aliases:
                drift.append(
                    f"API_ID MISMATCH: known='{api_id}' but matrix['{profile_key}'].api_id='{declared_api_id}'"
                )

    # Reverse check: matrix has profiles for unknown models?
    profile_keys = {info["profile_key"] for info in KNOWN_CURRENT_MODELS.values()}
    for key in matrix:
        if key in {"version", "date", "api_breaking_changes", "fallback_rules",
                   "universal_for_all_claude_4x_models"}:
            continue
        if key in KNOWN_LEGACY_PROFILE_KEYS:
            continue
        if isinstance(matrix[key], dict) and key not in profile_keys:
            drift.append(f"STALE PROFILE: matrix has '{key}' but it's not in KNOWN_CURRENT_MODELS")

    print("Model Currency Check")
    print("=" * 60)
    print(f"Matrix:        {MATRIX_PATH.relative_to(SKILL_DIR)}")
    print(f"Matrix version: {matrix.get('version', '?')} ({matrix.get('date', '?')})")
    print(f"Known current: {len(KNOWN_CURRENT_MODELS)} models")
    print()

    if not drift:
        print("PASS: every known-current Anthropic model has a profile cell.")
        for api_id in KNOWN_CURRENT_MODELS:
            print(f"  ok  {api_id}")
        sys.exit(0)
    else:
        print(f"FAIL: {len(drift)} drift signal(s) detected:")
        for line in drift:
            print(f"  - {line}")
        print()
        print("Fix: update KNOWN_CURRENT_MODELS in this script + add/correct profile in modulation-matrix.yaml.")
        sys.exit(1)


if __name__ == "__main__":
    main()
