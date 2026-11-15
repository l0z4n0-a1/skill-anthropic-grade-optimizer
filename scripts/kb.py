#!/usr/bin/env python3
"""Read the knowledge base: print the claims that matter for one review, and nothing else.

The knowledge base holds several hundred claims and a review uses a fraction of
them. This script selects by topic and by model. A topic can still hold a hundred
claims, so read in two passes: `--brief` for one line per claim, then `cite` for
the full record of the ones the review turns on.

Usage:
  kb.py topics                         list topics with claim counts
  kb.py models                         list model ids that have model-specific claims
  kb.py show TOPIC[,TOPIC...] [--model ID] [--kind fact|behavior|practice] [--grep TEXT] [--brief] [--quotes]
  kb.py model ID [--brief]             every claim tied to that model id
  kb.py core [QUESTION]                the short first read for one review question; no argument lists them
  kb.py cite ID[,ID...]                full records, with quote and source URL, for a report

`show` prints claims that apply to every model plus, with --model, those tied to
that model. Claims tied only to other models are left out.

In:  kb/claims/*.jsonl, kb/core.json, kb/sources.json, kb/snapshots.lock.json
Out: text on stdout. Exit 1 when the selection is empty or an id is unknown.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

KB = pathlib.Path(__file__).resolve().parent.parent / "kb"
GENERAL = {"all", "claude-code"}


def load() -> list:
    claims = []
    for path in sorted((KB / "claims").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                claims.append(json.loads(line))
    return claims


def source_ref(sid: str) -> str:
    sources = {s["id"]: s for s in json.loads((KB / "sources.json").read_text(encoding="utf-8"))}
    lock = json.loads((KB / "snapshots.lock.json").read_text(encoding="utf-8")) if (KB / "snapshots.lock.json").exists() else {}
    src = sources.get(sid, {})
    where = src.get("url") or ("claude-api skill bundled with Claude Code: " + src.get("bundled", "?"))
    return f"{where} (snapshot of {lock.get(sid, {}).get('fetched', 'unknown date')})"


def applies(claim: dict, model: str) -> bool:
    """`model` may name several ids, comma-separated, for a piece that more than one model reads."""
    scope = set(claim["applies_to"])
    return bool(scope & GENERAL) or bool(scope & {m for m in model.split(",") if m})


def line(claim: dict, quotes: bool, brief: bool = False) -> str:
    scope = "" if set(claim["applies_to"]) & GENERAL else f" [{', '.join(claim['applies_to'])}]"
    if brief:
        return f"{claim['id']}{scope}: {claim['claim']}"
    text = f"{claim['id']} ({claim['kind']}){scope}: {claim['claim']}\n    why: {claim['why']}\n    check: {claim['check']}"
    return text + (f"\n    quote: \"{claim['quote']}\"\n    source: {source_ref(claim['source'])}" if quotes else "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Query the knowledge base.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("topics")
    sub.add_parser("models")
    show = sub.add_parser("show")
    show.add_argument("topics")
    show.add_argument("--model", default="")
    show.add_argument("--kind", default="")
    show.add_argument("--grep", default="")
    show.add_argument("--quotes", action="store_true")
    show.add_argument("--brief", action="store_true", help="one line per claim: id and claim only")
    one = sub.add_parser("model")
    one.add_argument("id")
    one.add_argument("--brief", action="store_true", help="one line per claim: id and claim only")
    core = sub.add_parser("core")
    core.add_argument("question", nargs="?", default="")
    cite = sub.add_parser("cite")
    cite.add_argument("ids")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    claims = load()

    if args.cmd == "topics":
        counts = collections.Counter(c["topic"] for c in claims)
        print("\n".join(f"{t:14} {n}" for t, n in sorted(counts.items())) + f"\n{'total':14} {len(claims)}")
        return 0
    if args.cmd == "models":
        counts = collections.Counter(m for c in claims for m in c["applies_to"] if m not in GENERAL)
        print("\n".join(f"{m:22} {n}" for m, n in sorted(counts.items())))
        return 0
    if args.cmd == "core":
        questions = json.loads((KB / "core.json").read_text(encoding="utf-8"))
        if not args.question:
            print("\n".join(f"{name:13} {len(q['claims']):>2} claims  {q['principle']}" for name, q in questions.items()))
            return 0
        if args.question not in questions:
            print("unknown question; choose from: " + ", ".join(questions), file=sys.stderr)
            return 1
        by_id = {c["id"]: c for c in claims}
        print(f"What Anthropic's documentation says, in short: {questions[args.question]['principle']}\n")
        print("\n".join(line(by_id[i], False) for i in questions[args.question]["claims"]))
        print(f"\n{len(questions[args.question]['claims'])} core claims; `show` lists the rest of a topic")
        return 0
    if args.cmd == "model":
        picked = [c for c in claims if args.id in c["applies_to"]]
        quotes = False
    elif args.cmd == "cite":
        wanted = [i for i in args.ids.split(",") if i]
        by_id = {c["id"]: c for c in claims}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            print("unknown claim ids: " + ", ".join(missing), file=sys.stderr)
            return 1
        picked, quotes = [by_id[i] for i in wanted], True
    else:
        topics = set(args.topics.split(","))
        needle = args.grep.lower()
        picked = [c for c in claims if c["topic"] in topics and applies(c, args.model)
                  and (not args.kind or c["kind"] == args.kind)
                  and (not needle or needle in (c["claim"] + c["why"] + c["check"]).lower())]
        quotes = args.quotes
    if not picked:
        print("no claims match", file=sys.stderr)
        return 1
    print("\n".join(line(c, quotes, getattr(args, "brief", False)) for c in picked))
    print(f"\n{len(picked)} claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
