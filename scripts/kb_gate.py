#!/usr/bin/env python3
"""Gate for the knowledge base: every claim must quote its source verbatim.

In:  kb/claims/*.jsonl (one claim per line), kb/sources.json, kb/snapshots/<source>.md
Out: a count per file on stdout; with --json, a machine-readable report.
Fails: exit 1 when any claim has a missing or invalid field, a duplicate id, an
       unknown source, or a quote that is not in the snapshot. Exit 2 when a
       snapshot is absent (run kb_fetch.py first) - that is "cannot check", not "passed".

A quote matches when it appears in the snapshot after collapsing whitespace and
normalising typographic quotes and dashes. Markdown markers are part of the text:
quote the source as written, or pick a span without markup.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KB = ROOT / "kb"
TOPICS = {"prompting", "model", "context", "cost", "skills", "subagents", "hooks", "mcp",
          "plugins", "settings", "orchestration", "tools", "evals", "harness"}
KINDS = {"fact", "behavior", "practice"}
REQUIRED = ("id", "topic", "kind", "applies_to", "claim", "why", "check", "quote", "source")
MAX_QUOTE = 400
MIN_QUOTE = 25
MIN_WORD_CHARS = 18
_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " ", "‑": "-"})


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_TRANS)).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sources = {s["id"] for s in json.loads((KB / "sources.json").read_text(encoding="utf-8"))}
    files = [pathlib.Path(f) for f in args.files] or sorted((KB / "claims").glob("*.jsonl"))
    snaps: dict[str, str] = {}
    seen: dict[str, str] = {}
    errors: list[str] = []
    missing_snap: set[str] = set()
    report = {}

    for path in files:
        ok = 0
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{path.name}:{n}"
            try:
                c = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{where} invalid JSON: {exc}")
                continue
            bad = [k for k in REQUIRED if not c.get(k)]
            if bad:
                errors.append(f"{where} missing {bad}")
                continue
            cid = c["id"]
            if cid in seen:
                errors.append(f"{where} duplicate id {cid} (also {seen[cid]})")
                continue
            seen[cid] = where
            if c["topic"] not in TOPICS or c["kind"] not in KINDS:
                errors.append(f"{where} {cid} bad topic/kind: {c['topic']}/{c['kind']}")
                continue
            if not isinstance(c["applies_to"], list):
                errors.append(f"{where} {cid} applies_to must be a list")
                continue
            if c["source"] not in sources:
                errors.append(f"{where} {cid} unknown source {c['source']}")
                continue
            # Measured after normalising and on letters and digits, so padding cannot stand in for a quote.
            quote = norm(str(c["quote"]))
            if not MIN_QUOTE <= len(quote) <= MAX_QUOTE or sum(ch.isalnum() for ch in quote) < MIN_WORD_CHARS:
                errors.append(f"{where} {cid} quote must be {MIN_QUOTE}-{MAX_QUOTE} characters with at least "
                              f"{MIN_WORD_CHARS} letters or digits (got {len(quote)})")
                continue
            if c["source"] not in snaps:
                snap = KB / "snapshots" / f"{c['source']}.md"
                if not snap.exists():
                    missing_snap.add(c["source"])
                    continue
                snaps[c["source"]] = norm(snap.read_text(encoding="utf-8", errors="replace"))
            if norm(c["quote"]) not in snaps[c["source"]]:
                errors.append(f"{where} {cid} quote not in {c['source']}: {c['quote'][:70]!r}")
                continue
            ok += 1
        report[path.name] = ok

    if not errors and not missing_snap and sum(report.values()) == 0:
        errors.append("no claims were checked; an empty knowledge base is not a pass")

    if args.json:
        print(json.dumps({"ok": report, "errors": errors, "missing_snapshots": sorted(missing_snap)}, indent=2))
    else:
        for name, ok in report.items():
            print(f"{name}: {ok} claims verified")
        print(f"total verified={sum(report.values())} errors={len(errors)} missing_snapshots={len(missing_snap)}")
        for e in errors:
            print("  x", e)
        for m in sorted(missing_snap):
            print("  ? no snapshot for", m)
    if errors:
        return 1
    return 2 if missing_snap else 0


if __name__ == "__main__":
    raise SystemExit(main())
