#!/usr/bin/env python3
"""Read the knowledge base: print the claims that matter for one review, and nothing else.

The knowledge base holds more than a thousand claims and a review uses a fraction of
them. This script selects by topic and by model. A topic can still hold a hundred
claims, so read in two passes: `--brief` for one line per claim, then `cite` for
the full record of the ones the review turns on.

Usage:
  kb.py topics                         list topics with claim counts
  kb.py models                         list model ids that have model-specific claims
  kb.py show TOPIC[,TOPIC...] [--model ID[,ID...]] [--kind fact|behavior|practice] [--grep TEXT] [--brief] [--quotes]
  kb.py model ID [--brief]             every claim tied to that model id
  kb.py core [QUESTION]                the short first read for one review question; no argument lists them
  kb.py cite ID[,ID...]                full records, with quote and source, for a report

`show` prints claims that apply to every model plus, with --model, those tied to
that model. Claims tied only to other models are left out. A model id that no claim
names is not an error (the knowledge base may predate that model): `show` says so on
stderr and prints the general claims.

In:  kb/claims/*.jsonl, kb/core.json, kb/sources.json, kb/snapshots.lock.json, kb/pending.json
Out: text on stdout, for a person to read; its layout is not a stable interface. A claim whose source
     changed and was not yet re-reviewed carries a note saying so.
Fails: exit 0 claims printed; 1 the selection is valid and empty (nothing matches, or a model id no claim
       names); 2 an invalid value (unknown topic, claim id, core question, kind, or a model id that is not a
       model id) or bad arguments; 3 the knowledge base data is missing or malformed (run kb_gate.py).
Spaces around the commas of a list are ignored.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # before kb_gate is imported: reading the knowledge base must not write scripts/__pycache__

import argparse
import collections
import json
import pathlib

from kb_gate import REQUIRED, SCOPE

KB = pathlib.Path(__file__).resolve().parent.parent / "kb"
GENERAL = {"all", "claude-code"}
KINDS = ("fact", "behavior", "practice")
PENDING: dict = {}


class DataError(Exception):
    pass


def split_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def load() -> list:
    claims = []
    for path in sorted((KB / "claims").glob("*.jsonl")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                claim = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DataError(f"{path.name}:{n} is not valid JSON ({exc})") from exc
            if not isinstance(claim, dict) or any(k not in claim for k in REQUIRED):
                raise DataError(f"{path.name}:{n} is not a complete claim record")
            claims.append(claim)
    return claims


def source_ref(sid: str) -> str:
    sources = {s["id"]: s for s in json.loads((KB / "sources.json").read_text(encoding="utf-8"))}
    lock = json.loads((KB / "snapshots.lock.json").read_text(encoding="utf-8")) if (KB / "snapshots.lock.json").exists() else {}
    src = sources.get(sid, {})
    if "url" in src:
        where = src["url"]
    elif "bundled" in src:
        where = f"bundled with Claude Code (a file of the claude-api skill, no URL): {src['bundled']}"
    elif "path" in src:
        where = f"local file: {src['path']}"
    else:
        where = f"unknown source {sid}"
    return f"{where} (snapshot of {lock.get(sid, {}).get('fetched', 'unknown date')})"


def applies(claim: dict, model: str) -> bool:
    """`model` may name several ids, comma-separated, for a piece that more than one model reads."""
    scope = set(claim["applies_to"])
    return bool(scope & GENERAL) or bool(scope & set(split_list(model)))


def line(claim: dict, quotes: bool, brief: bool = False) -> str:
    scope = "" if set(claim["applies_to"]) & GENERAL else f" [{', '.join(claim['applies_to'])}]"
    since = PENDING.get(claim["source"])
    note = f" [source changed on {since}; claim not re-reviewed]" if since else ""
    if brief:
        return f"{claim['id']}{scope}: {claim['claim']}{note}"
    text = f"{claim['id']} ({claim['kind']}){scope}: {claim['claim']}{note}\n    why: {claim['why']}\n    check: {claim['check']}"
    return text + (f"\n    quote: \"{claim['quote']}\"\n    source: {source_ref(claim['source'])}" if quotes else "")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Query the knowledge base of claims extracted from Anthropic's documentation, engineering posts and attributed "
                    "talks. Output is text for a person. Exit 0 printed; 1 valid but empty selection; 2 invalid value or usage; "
                    "3 knowledge-base data missing or malformed.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")
    sub.add_parser("topics", help="list the topics with their claim counts", description="List the topics with their claim counts.")
    sub.add_parser("models", help="list the model ids that have model-specific claims",
                   description="List the model ids that have model-specific claims.")
    show = sub.add_parser("show", help="print the claims of one or more topics",
                          description="Print the claims of one or more topics: those that apply to every model, plus with --model "
                                      "those tied to the named models.")
    show.add_argument("topics", help="topic, or several separated by commas (see `topics`)")
    show.add_argument("--model", default="", help="model id, or several separated by commas, whose model-specific claims to include")
    show.add_argument("--kind", default=None, choices=KINDS, help="only claims of this kind")
    show.add_argument("--grep", default="", help="only claims whose text, why or check contains this (case-insensitive)")
    show.add_argument("--quotes", action="store_true", help="include each claim's quote and source")
    show.add_argument("--brief", action="store_true", help="one line per claim: id and claim only")
    one = sub.add_parser("model", help="print every claim tied to one model id", description="Print every claim tied to one model id.")
    one.add_argument("id", help="a model id such as claude-opus-5-5 (see `models`)")
    one.add_argument("--brief", action="store_true", help="one line per claim: id and claim only")
    core = sub.add_parser("core", help="print the short first read for one review question",
                          description="Print the short first read for one review question; with no argument, list the questions.")
    core.add_argument("question", nargs="?", default="", help="a question name from the list; omit to list them")
    cite = sub.add_parser("cite", help="print full records, with quote and source, for a report",
                          description="Print the full records of the claims, with quote and source, for a report.")
    cite.add_argument("ids", nargs="+", help="claim ids, separated by commas or spaces")
    return ap


def run(args, claims: list) -> int:
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
            return 2
        by_id = {c["id"]: c for c in claims}
        print(f"What Anthropic's published material says, in short: {questions[args.question]['principle']}\n")
        print("\n".join(line(by_id[i], False) for i in questions[args.question]["claims"]))
        print(f"\n{len(questions[args.question]['claims'])} core claims; `show` lists the rest of a topic")
        return 0
    known_models = {m for c in claims for m in c["applies_to"] if m not in GENERAL}
    if args.cmd == "model":
        if not SCOPE.match(args.id) or args.id in GENERAL:
            print(f"{args.id!r} is not a model id such as claude-opus-5-5; `kb.py models` lists the known ones", file=sys.stderr)
            return 2
        picked = [c for c in claims if args.id in c["applies_to"]]
        quotes = False
        empty = f"no claim is tied to {args.id}. Model ids with claims: " + ", ".join(sorted(known_models))
    elif args.cmd == "cite":
        wanted = [i for part in args.ids for i in split_list(part)]
        by_id = {c["id"]: c for c in claims}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            print("unknown claim ids: " + ", ".join(missing), file=sys.stderr)
            return 2
        picked, quotes = [by_id[i] for i in wanted], True
        empty = "no claim ids given"
    else:
        topics = set(split_list(args.topics))
        known_topics = sorted({c["topic"] for c in claims})
        bad = sorted(topics - set(known_topics))
        if bad or not topics:
            print(f"unknown topic(s): {', '.join(bad) or '(none given)'}. Topics: " + ", ".join(known_topics), file=sys.stderr)
            return 2
        models = split_list(args.model)
        malformed = [m for m in models if not SCOPE.match(m) or m in GENERAL]
        if malformed:
            print(f"not a model id: {', '.join(malformed)}. Model ids with claims: `kb.py models`", file=sys.stderr)
            return 2
        for m in models:
            if m not in known_models:
                print(f"note: no claim is tied to {m}; the knowledge base may predate it. Showing the general claims only.",
                      file=sys.stderr)
        needle = args.grep.lower()
        picked = [c for c in claims if c["topic"] in topics and applies(c, args.model)
                  and (not args.kind or c["kind"] == args.kind)
                  and (not needle or needle in (c["claim"] + c["why"] + c["check"]).lower())]
        quotes = args.quotes
        empty = "no claims match this combination of topic, model, kind and grep text"
    if not picked:
        print(empty, file=sys.stderr)
        return 1
    print("\n".join(line(c, quotes, getattr(args, "brief", False)) for c in picked))
    print(f"\n{len(picked)} claims")
    return 0


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        claims = load()
        pending = KB / "pending.json"
        PENDING.clear()
        if pending.exists():
            PENDING.update(json.loads(pending.read_text(encoding="utf-8")).get("sources", {}))
        return run(args, claims)
    except (DataError, json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(f"the knowledge base data is missing or malformed ({type(exc).__name__}: {exc}); "
              "run `python scripts/kb_gate.py` to find the record", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
