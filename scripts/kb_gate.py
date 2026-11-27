#!/usr/bin/env python3
"""Gate for the knowledge base: every claim must quote its source verbatim.

In:  kb/claims/*.jsonl (one claim per line), kb/sources.json, kb/snapshots/<source>.md, and
     when present kb/snapshots.lock.json, kb/index.lock.json, kb/pending.json.
     Optional file arguments limit which claim files are checked (limited coverage: say so
     when you report it); ids are still checked against every file in kb/claims/.
Out: a count per file on stdout; with --json, an object {ok: {file: verified count}, errors:
     [str], warnings: [str], missing_snapshots: [source id]}; the exit code is the verdict.
Fails: exit 0 every claim checked and the data files are well formed;
       1 something is wrong with the data: a claim with a missing, mistyped or invalid field,
         a duplicate id, an unknown source, a quote that is not in its snapshot, a snapshot
         that differs from the lock, a malformed sources.json, lock or pending.json;
       2 misuse: bad arguments, or a file argument that does not exist;
       3 cannot check: a snapshot is absent (run kb_update.py --apply, or kb_fetch.py, first) and
         nothing else is wrong. "Cannot check" is not "passed".
       Precedence: 2, then 1, then 3, then 0.

A claim record has the keys id, topic, kind, applies_to, claim, why, check, quote, source, all
non-empty strings except applies_to, a non-empty list of 'all', 'claude-code' or model ids such as
claude-opus-5-5, with an optional -YYYYMMDD date suffix (an alias and its dated id are two
different scope strings; nothing here resolves one to the other). The id is `<prefix>-<number>`
and unique across all of kb/claims/ even when only some files are checked.
sources.json: a list of {id, tier, topic, and exactly one of url, bundled, path}; ids are unique,
lower-case letters, digits and hyphens; tier is 1, 2 or 3.
snapshots.lock.json: {source id: {sha256, bytes, fetched (YYYY-MM-DD), source}}.
index.lock.json: {index url: [page urls]}. pending.json: {sources: {source id: date},
new_pages: {url: date}, removed_pages: {url: date}}.

A quote matches when it appears in the snapshot after collapsing whitespace and
normalising typographic quotes and dashes. Markdown markers are part of the text:
quote the source as written, or pick a span without markup. The quote must be
MIN_QUOTE to MAX_QUOTE characters after that and hold at least MIN_ALNUM_CHARS letters or
digits, so that padding cannot stand in for a quote.

Warns, without failing, when the claim sentence contains a number its source
never prints: usually a sum, a percentage or a year the extractor derived. A
warning is a claim to read again, since a claim may rightly cite a second
source's figure. Whether a claim says what its source says is not checked here;
references/maintaining.md gives that to a second reader.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
MIN_ALNUM_CHARS = 18
TIERS = {1, 2, 3}
LOCATORS = ("url", "bundled", "path")
CLAIM_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*-\d+$")
SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SCOPE = re.compile(r"^(all|claude-code|claude-[a-z]+-\d+(-\d{1,2})?(-\d{8})?)$")
_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " ", "‑": "-"})


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_TRANS)).strip()


_NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?(?:[kKmM]|%|x)?(?!\w)")
_MODEL_ID = re.compile(r"claude-[a-z]+-\d+(?:-\d{1,2})?(?:-\d{8})?")
_WORDS = dict(zip("0 1 2 3 4 5 6 7 8 9 10 11 12".split(),
                  "zero one two three four five six seven eight nine ten eleven twelve".split()))


def numbers_not_in_source(claim: str, snapshot: str) -> list[str]:
    """Numbers in the claim sentence that the snapshot prints neither as digits nor, up to twelve, as a word."""
    plain = snapshot.replace(",", "").lower()
    absent = []
    for found in _NUMBER.finditer(_MODEL_ID.sub("", claim)):
        core = found.group(0).replace(",", "").lstrip("$").rstrip("%xkKmM")
        if not core or re.search(rf"(?<![\d.]){re.escape(core)}(?!\d)", plain):
            continue
        if core in _WORDS and re.search(rf"\b{_WORDS[core]}\b", plain):
            continue
        absent.append(found.group(0))
    return absent


def _load(path: pathlib.Path, errors: list[str], required: bool = False):
    """Parsed JSON, or None with an error recorded when the file is malformed (or absent and required)."""
    if not path.exists():
        if required:
            errors.append(f"{path.name} is missing; run the gate from a checkout of the repository")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        errors.append(f"{path.name} cannot be read: {exc}")
        return None


def _is_date(value) -> bool:
    try:
        return isinstance(value, str) and dt.date.fromisoformat(value) is not None
    except ValueError:
        return False


def check_sources(kb: pathlib.Path, errors: list[str]) -> set[str]:
    """Validate sources.json; returns the ids with a usable shape."""
    raw = _load(kb / "sources.json", errors, required=True)
    ids: set[str] = set()
    if raw is None:
        return ids
    if not isinstance(raw, list):
        errors.append("sources.json must be a list of sources")
        return ids
    for i, src in enumerate(raw):
        where = f"sources.json[{i}]"
        if not isinstance(src, dict):
            errors.append(f"{where} must be an object")
            continue
        sid = src.get("id")
        if not isinstance(sid, str) or not SOURCE_ID.match(sid):
            errors.append(f"{where} id must be lower-case letters, digits and hyphens (got {sid!r})")
            continue
        if sid in ids:
            errors.append(f"{where} duplicate source id {sid}")
            continue
        ids.add(sid)
        found = [k for k in LOCATORS if k in src]
        if len(found) != 1:
            errors.append(f"{where} {sid} needs exactly one of {', '.join(LOCATORS)} (has {found or 'none'})")
        elif not isinstance(src[found[0]], str) or not src[found[0]].strip():
            errors.append(f"{where} {sid} {found[0]} must be a non-empty string")
        elif found[0] == "url" and not src["url"].startswith(("https://", "http://")):
            errors.append(f"{where} {sid} url must start with https:// or http://")
        if isinstance(src.get("tier"), bool) or src.get("tier") not in TIERS:
            errors.append(f"{where} {sid} tier must be one of {sorted(TIERS)} (got {src.get('tier')!r})")
        if not isinstance(src.get("topic"), str) or not src["topic"].strip():
            errors.append(f"{where} {sid} needs a topic")
    return ids


def check_state(kb: pathlib.Path, ids: set[str], errors: list[str]) -> dict:
    """Validate the two locks and pending.json when they exist; returns the snapshot lock ({} if unusable)."""
    lock = _load(kb / "snapshots.lock.json", errors)
    if lock is not None and not isinstance(lock, dict):
        errors.append("snapshots.lock.json must be an object keyed by source id")
        lock = None
    for sid, entry in (lock or {}).items():
        where = f"snapshots.lock.json {sid}"
        if sid not in ids:
            errors.append(f"{where}: not a source in sources.json")
        if not isinstance(entry, dict):
            errors.append(f"{where}: entry must be an object")
            continue
        if not (isinstance(entry.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            errors.append(f"{where}: sha256 must be 64 hex digits")
        if isinstance(entry.get("bytes"), bool) or not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            errors.append(f"{where}: bytes must be a non-negative integer")
        if not _is_date(entry.get("fetched")):
            errors.append(f"{where}: fetched must be a YYYY-MM-DD date")
        if not isinstance(entry.get("source"), str):
            errors.append(f"{where}: source must be a string")
    index = _load(kb / "index.lock.json", errors)
    if index is not None and not (isinstance(index, dict) and all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(u, str) for u in v) for k, v in index.items())):
        errors.append("index.lock.json must map each index url to a list of page urls")
    pending = _load(kb / "pending.json", errors)
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) - {"sources", "new_pages", "removed_pages"}:
            errors.append("pending.json must be an object with only sources, new_pages and removed_pages")
        else:
            for key, items in pending.items():
                if not isinstance(items, dict) or not all(isinstance(k, str) and _is_date(v) for k, v in items.items()):
                    errors.append(f"pending.json {key} must map ids or urls to YYYY-MM-DD dates")
                elif key == "sources":
                    errors += [f"pending.json: {sid} is not a source in sources.json" for sid in items if sid not in ids]
    return lock if isinstance(lock, dict) else {}


def claim_ids_elsewhere(kb: pathlib.Path, checked: list[pathlib.Path]) -> dict[str, str]:
    """id -> file:line for claims in kb/claims/ files that are not being checked, read leniently."""
    skip = {p.resolve() for p in checked}
    found: dict[str, str] = {}
    for path in sorted((kb / "claims").glob("*.jsonl")):
        if path.resolve() in skip:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            try:
                found.setdefault(json.loads(line)["id"], f"{path.name}:{n}")
            except (ValueError, KeyError, TypeError):
                continue
    return found


def run(kb: pathlib.Path, files: list[pathlib.Path] | None = None) -> dict:
    """Check the knowledge base in `kb`. Returns {ok, errors, warnings, missing_snapshots} (see the module docstring)."""
    errors: list[str] = []
    warnings: list[str] = []
    ids = check_sources(kb, errors)
    lock = check_state(kb, ids, errors)
    explicit = files is not None
    files = files if explicit else sorted((kb / "claims").glob("*.jsonl"))
    if not files:
        errors.append("kb/claims/ holds no .jsonl files")
    snaps: dict[str, str] = {}
    seen: dict[str, str] = dict(claim_ids_elsewhere(kb, files)) if explicit else {}
    missing_snap: set[str] = set()
    stale_snap: set[str] = set()
    report = {}

    for path in files:
        ok = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path.name} cannot be read: {exc}")
            report[path.name] = 0
            continue
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            where = f"{path.name}:{n}"
            try:
                c = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{where} invalid JSON: {exc}")
                continue
            if not isinstance(c, dict):
                errors.append(f"{where} a claim must be a JSON object")
                continue
            bad = [k for k in REQUIRED if not c.get(k)]
            if bad:
                errors.append(f"{where} missing {bad}")
                continue
            wrong = [k for k in REQUIRED if k != "applies_to" and not isinstance(c[k], str)]
            if wrong:
                errors.append(f"{where} {c['id']} these keys must be strings: {wrong}")
                continue
            cid = c["id"]
            if not CLAIM_ID.match(cid):
                errors.append(f"{where} id {cid!r} must look like <prefix>-<number>, such as hooks-012")
                continue
            if cid in seen:
                errors.append(f"{where} duplicate id {cid} (also {seen[cid]})")
                continue
            seen[cid] = where
            if c["topic"] not in TOPICS or c["kind"] not in KINDS:
                errors.append(f"{where} {cid} bad topic/kind: {c['topic']}/{c['kind']}")
                continue
            if not isinstance(c["applies_to"], list) or not all(isinstance(s, str) and SCOPE.match(s) for s in c["applies_to"]):
                errors.append(f"{where} {cid} applies_to must list 'all', 'claude-code' or model ids such as "
                              "claude-opus-5-5 (optionally with a -YYYYMMDD suffix)")
                continue
            if c["source"] not in ids:
                errors.append(f"{where} {cid} unknown source {c['source']}")
                continue
            # Measured after normalising and on letters and digits, so padding cannot stand in for a quote.
            quote = norm(c["quote"])
            if not MIN_QUOTE <= len(quote) <= MAX_QUOTE or sum(ch.isalnum() for ch in quote) < MIN_ALNUM_CHARS:
                errors.append(f"{where} {cid} quote must be {MIN_QUOTE}-{MAX_QUOTE} characters with at least "
                              f"{MIN_ALNUM_CHARS} letters or digits (got {len(quote)})")
                continue
            if c["source"] not in snaps:
                snap = kb / "snapshots" / f"{c['source']}.md"
                if not snap.exists():
                    missing_snap.add(c["source"])
                    continue
                locked = lock.get(c["source"], {}).get("sha256") if isinstance(lock.get(c["source"]), dict) else None
                if locked and hashlib.sha256(snap.read_bytes()).hexdigest() != locked:
                    stale_snap.add(c["source"])
                snaps[c["source"]] = norm(snap.read_text(encoding="utf-8", errors="replace"))
            if quote not in snaps[c["source"]]:
                errors.append(f"{where} {cid} quote not in {c['source']}: {c['quote'][:70]!r}")
                continue
            absent = numbers_not_in_source(c["claim"], snaps[c["source"]])
            if absent:
                warnings.append(f"{where} {cid} claim has a number {c['source']} does not print: {', '.join(absent)}")
            ok += 1
        report[path.name] = ok
        if ok == 0 and not any(path.name in e for e in errors) and not missing_snap:
            errors.append(f"{path.name} holds no claims")
    for sid in sorted(stale_snap):
        errors.append(f"snapshot {sid} differs from snapshots.lock.json, so it is not the text the lock recorded: restore it with "
                      f"`kb_update.py --apply` or `kb_fetch.py --only {sid}` (a source that changed outside is then recorded as pending)")

    if not errors and not missing_snap and sum(report.values()) == 0:
        errors.append("no claims were checked; an empty knowledge base is not a pass")
    return {"ok": report, "errors": errors, "warnings": warnings, "missing_snapshots": sorted(missing_snap)}


def exit_code(result: dict) -> int:
    return 1 if result["errors"] else 3 if result["missing_snapshots"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check that every claim in the knowledge base quotes its source verbatim.",
                                 epilog="exit 0 verified; 1 a claim or data file is wrong; 2 misuse; 3 a snapshot is absent, "
                                        "so nothing could be checked for that source (kb_update.py --apply fetches it)")
    ap.add_argument("--json", action="store_true", help="print {ok, errors, warnings, missing_snapshots} as JSON instead of text")
    ap.add_argument("files", nargs="*", help="claim files to check (default: all of kb/claims/*.jsonl); limited coverage, "
                                              "but ids are still checked against every claim file")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    files = [pathlib.Path(f) for f in args.files] or None
    absent = [str(f) for f in files or [] if not f.is_file()]
    if absent:
        print(f"not a file: {', '.join(absent)}", file=sys.stderr)
        return 2
    result = run(KB, files)
    code = exit_code(result)
    if args.json:
        print(json.dumps(result, indent=2))
        return code
    for name, ok in result["ok"].items():
        print(f"{name}: {ok} claims verified")
    print(f"total verified={sum(result['ok'].values())} errors={len(result['errors'])} "
          f"missing_snapshots={len(result['missing_snapshots'])} warnings={len(result['warnings'])}")
    for e in result["errors"]:
        print("  x", e)
    for w in result["warnings"]:
        print("  !", w)
    for m in result["missing_snapshots"]:
        print("  ? no snapshot for", m)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
