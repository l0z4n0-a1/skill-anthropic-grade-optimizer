#!/usr/bin/env python3
"""Say what changed in the documentation since the last update, and what it affects.

In:  kb/sources.json, kb/snapshots.lock.json, kb/index.lock.json ({index_url: [sorted urls]}),
     kb/pending.json, kb/claims/*.jsonl, kb/core.json, kb/harness.json. Downloads each source
     with a `url` and the two documentation indexes in INDEXES.
Out: a report on stdout, as text or with --json as one object (also written to --out FILE, which
     must be outside the plugin directory). Only a run that gets as far as comparing emits a report:
     --reviewed and a usage error (exit 2) print a one-line message and no JSON.
     JSON keys (schema_version 1; a key is never removed within a version, new ones may be added):
       schema_version  int, 1.
       lock_oldest, lock_newest   str YYYY-MM-DD or null: the fetch dates (UTC) of the oldest and
                       newest snapshot in the lock. Not review dates.
       changed_sources [{id, url, claims: int, core_or_harness_ids: [str], new: bool}] downloaded
                       hash differs from the lock; `new` means the source has no lock entry.
       pending         {sources: [{id, since, claims, core_or_harness_ids}], new_pages: [{url, since}],
                       removed_pages: [{url, since}]}: fetched earlier, not yet released by --reviewed.
       unchanged [id]; failed [{id, error}] (a source id or an index url); not_checked [{id, reason}];
       not_compared {sources, claims}: bundled or local sources skipped for want of --bundled-dir,
                       and the claims that rest on them.
       new_pages, removed_pages [{index, url}]; no_index_baseline [index url];
       snapshot_mismatch [id]: a local snapshot whose hash differs from the lock;
       unreadable_claim_lines int; incomplete [str]: why the comparison was not complete;
       compared int: sources and indexes actually compared.
       restored_snapshots [id], no_previous [id]: set by --apply (empty otherwise). `no_previous` are the
                       changed sources whose previous snapshot could not be kept because the local file was
                       absent or did not match the lock: read those sources whole, there is no diff.
       applied bool: --apply wrote files. exit int: the exit code.
Fails: exit 2 misuse, decided before any request: --apply or --reviewed outside a working clone (no .git,
         a plugin cache, an unwritable kb/), an unknown --only id, --out inside the plugin, --partial
         without --apply, an option --reviewed would ignore, --reviewed of an item that is not pending or
         while the gate fails or a snapshot to release is absent, or a selection that compared nothing;
       1 a download failed and nothing could be compared;
       3 there is work: a changed source, a new or removed page, or a pending item;
       4 nothing changed was seen but the comparison was incomplete (a download failed, an index has no
         baseline, a local snapshot differs from the lock, a claim line was unreadable);
       0 the declared scope was compared completely and nothing changed or is pending.
       Precedence: 2, 1, 3, 4, 0. A partial failure shows in the report and, with work present, stays exit 3.
       A removed page alone is work. Failed sources keep their lock entry.

Two baselines. The lock says what was downloaded; kb/pending.json says what was downloaded but not
yet re-read. --apply writes in this order, each file by temporary file and os.replace: pending.json
first (so a run cut short still flags what it was about to change; only a source that already had a
lock entry is pending, a new source is not), then the previous snapshot of each changed source into
kb/snapshots-prev/<id>.md (only if the local file matches the lock), then the snapshots, then
index.lock.json, and snapshots.lock.json last. Pending accumulates until `--reviewed ID[,ID...]|all`
removes items; --reviewed first runs the gate and refuses unless it reports no errors and every snapshot
to release exists. So an update that stops halfway keeps flagging its claims: the check reports pending
items as work even when today's bytes match.

Modes:
  default   reads the plugin and writes nothing inside it, so it runs from an installed copy that
            is read-only and has no kb/snapshots/. Run it as `python -B` so that no bytecode is
            written either; the script also sets that flag itself before importing kb_fetch.
  --apply   for a working clone only (kb/ writable, .git present, path not under plugins/cache).
            Writes the changed snapshots (and restores a missing or altered snapshot of an
            unchanged source). Applies nothing when a source failed, unless --partial. Does not run the
            gate: it prints the command to run next.

Usage: kb_update.py [--json] [--out FILE] [--apply [--partial]] [--only ID[,ID...]] [--bundled-dir DIR] [--max-seconds N]
       kb_update.py --reviewed ID[,ID...]|all
Network: GET requests only, to the hosts of the urls in kb/sources.json and of INDEXES, with the fixed
User-Agent of kb_fetch, a timeout of kb_fetch.TIMEOUT seconds per request, at most kb_fetch.MAX_BYTES per
response, and --max-seconds in all: each request's timeout is cut to what is left of the budget and a body
still arriving at the deadline is abandoned, so the run ends near it (a source not started or not finished in
time is reported as failed; name resolution is not interruptible). A redirect to any other host is refused. No review data, claim, setup or local path is sent; the host still sees what any
connection shows, such as the IP address. Reading a `bundled` or `path` file is local and sends nothing.
An index whose response parses into no urls, or into fewer than half of the baseline's, is not accepted as
the new baseline: it is listed as failed.
Known limits: two updates run at once are not locked against each other; an HTML source is hashed
after its text is extracted, so a changed link target under identical text hashes identically; the index
comparison sees absolute markdown link targets only, not changed descriptions.
Stdlib only.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # before kb_fetch is imported: a check must not leave scripts/__pycache__

import argparse
import json
import pathlib
import re
import tempfile
import time

import kb_fetch
import kb_gate

SCHEMA_VERSION = 1
ROOT = pathlib.Path(__file__).resolve().parent.parent
KB = ROOT / "kb"
INDEXES = ("https://platform.claude.com/llms.txt", "https://code.claude.com/docs/llms.txt")
MAX_SECONDS = 600
SHOW = 40
_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
read_json, write_json, atomic_write, sha = kb_fetch.read_json, kb_fetch.write_json, kb_fetch.atomic_write, kb_fetch.sha


def index_urls(body: bytes) -> list[str]:
    """The URLs of the markdown links in an llms.txt index, sorted and without repeats."""
    return sorted(set(_LINK.findall(body.decode("utf-8", errors="replace"))))


def kb_writable() -> bool:
    try:
        with tempfile.TemporaryFile(dir=KB):
            return True
    except OSError:
        return False


def clone_problem() -> str:
    """Why --apply must not run here, or an empty string. The root is the parent of kb/."""
    root = KB.parent
    if "plugins/cache" in root.resolve().as_posix().lower():
        return f"{root} is inside a plugin cache; update the plugin from its marketplace instead"
    if not (root / ".git").exists():
        return f"{root} has no .git; --apply only runs in a working clone of the repository"
    if not kb_writable():
        return f"{KB} is not writable; run it from a writable clone of the repo"
    return ""


def claim_counts() -> tuple[dict[str, list[str]], int]:
    """(source id -> ids of the claims that cite it, count of lines that could not be read)."""
    by_source: dict[str, list[str]] = {}
    unreadable = 0
    for path in sorted((KB / "claims").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                claim = json.loads(line)
                by_source.setdefault(claim["source"], []).append(claim["id"])
            except (json.JSONDecodeError, KeyError, TypeError):
                unreadable += 1
    return by_source, unreadable


def pinned_ids() -> set[str]:
    """Claim ids that kb/core.json or kb/harness.json depend on."""
    ids: set[str] = set()
    for entry in read_json(KB / "core.json", {}).values():
        if isinstance(entry, dict):
            ids.update(entry.get("claims", []))
    for entry in read_json(KB / "harness.json", {}).values():
        if isinstance(entry, dict) and entry.get("claim"):
            ids.add(entry["claim"])
    return ids


def check(args) -> tuple[dict, dict, dict, dict]:
    """Compare the outside with the locks. Returns (report, bodies of changed sources, bodies to restore, index url lists)."""
    sources = read_json(KB / "sources.json", [])
    lock = read_json(KB / "snapshots.lock.json", {})
    index_lock = read_json(KB / "index.lock.json", {})
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    cited, unreadable = claim_counts()
    pinned = pinned_ids()
    hosts = kb_fetch.hosts_of([s["url"] for s in sources if "url" in s] + list(INDEXES))
    deadline = time.monotonic() + (args.max_seconds or MAX_SECONDS)
    fetched_on = sorted(v["fetched"] for v in lock.values() if v.get("fetched"))
    report = {"schema_version": SCHEMA_VERSION,
              "lock_oldest": fetched_on[0] if fetched_on else None, "lock_newest": fetched_on[-1] if fetched_on else None,
              "changed_sources": [], "pending": {"sources": [], "new_pages": [], "removed_pages": []},
              "unchanged": [], "failed": [], "not_checked": [], "not_compared": {"sources": 0, "claims": 0},
              "new_pages": [], "removed_pages": [], "no_index_baseline": [], "snapshot_mismatch": [],
              "unreadable_claim_lines": unreadable, "incomplete": [], "compared": 0,
              "restored_snapshots": [], "no_previous": []}
    bodies: dict[str, bytes] = {}
    restore: dict[str, bytes] = {}
    out_of_time = f"time budget of {args.max_seconds or MAX_SECONDS} s used up before this download"

    for src in sources:
        sid = src["id"]
        if only and sid not in only:
            continue
        if "url" not in src and not args.bundled_dir:
            report["not_checked"].append({"id": sid, "reason":"bundled or local file; needs --bundled-dir"})
            report["not_compared"]["sources"] += 1
            report["not_compared"]["claims"] += len(cited.get(sid, []))
            continue
        if "url" not in src and "bundled" not in src and "path" not in src:
            report["not_checked"].append({"id": sid, "reason":"no url, path or bundled in sources.json"})
            continue
        if time.monotonic() > deadline:
            report["failed"].append({"id": sid, "error":out_of_time})
            continue
        try:
            body = kb_fetch.read_source(src, args.bundled_dir, hosts, deadline)
        except kb_fetch.NET_ERRORS as exc:
            report["failed"].append({"id": sid, "error":str(exc)})
            continue
        report["compared"] += 1
        digest = sha(body)
        if digest == lock.get(sid, {}).get("sha256"):
            report["unchanged"].append(sid)
            local = KB / "snapshots" / f"{sid}.md"
            if local.exists() and sha(local.read_bytes()) != digest:
                report["snapshot_mismatch"].append(sid)
            if args.apply and (not local.exists() or sid in report["snapshot_mismatch"]):
                restore[sid] = body
            continue
        if args.apply:
            bodies[sid] = body
        ids = cited.get(sid, [])
        report["changed_sources"].append({"id": sid, "url": kb_fetch.source_label(src),
                                          "claims": len(ids), "core_or_harness_ids": sorted(set(ids) & pinned),
                                          "new": sid not in lock})

    urls_now: dict[str, list[str]] = {}
    for index in () if only else INDEXES:
        if time.monotonic() > deadline:
            report["failed"].append({"id": index, "error":out_of_time})
            continue
        try:
            urls = index_urls(kb_fetch.http_get(index, hosts=hosts, deadline=deadline))
            before = index_lock.get(index)
            if not urls or (before and len(urls) * 2 < len(before)):
                raise ValueError(f"index parsed into {len(urls)} urls (baseline {len(before or [])}); response not accepted")
        except kb_fetch.NET_ERRORS as exc:
            report["failed"].append({"id": index, "error":str(exc)})
            continue
        urls_now[index] = urls
        if before is None:
            report["no_index_baseline"].append(index)
            continue
        report["compared"] += 1
        report["new_pages"] += [{"index": index, "url": u} for u in sorted(set(urls) - set(before))]
        report["removed_pages"] += [{"index": index, "url": u} for u in sorted(set(before) - set(urls))]

    pending = kb_fetch.read_pending(KB)
    for sid, since in sorted(pending["sources"].items()):
        if only and sid not in only:
            continue
        ids = cited.get(sid, [])
        report["pending"]["sources"].append({"id": sid, "since": since, "claims": len(ids),
                                             "core_or_harness_ids": sorted(set(ids) & pinned)})
    if not only:
        for key in ("new_pages", "removed_pages"):
            report["pending"][key] = [{"url": u, "since": d} for u, d in sorted(pending[key].items())]

    for label, items in (("a source or index failed to download", report["failed"]),
                         ("an index has no baseline", report["no_index_baseline"]),
                         ("a local snapshot differs from the lock", report["snapshot_mismatch"]),
                         ("claim lines could not be read, so impact counts are low", unreadable)):
        if items:
            report["incomplete"].append(label)
    work = (report["changed_sources"] or report["new_pages"] or report["removed_pages"]
            or any(report["pending"].values()))
    report["exit"] = 1 if report["failed"] and not report["compared"] else 3 if work else 4 if report["incomplete"] else 0
    return report, bodies, restore, urls_now


def apply(report: dict, bodies: dict, restore: dict, urls_now: dict) -> None:
    """Order matters: pending first, so a run cut short still flags what it changed; the lock last."""
    sources = {s["id"]: s for s in read_json(KB / "sources.json", [])}
    lock = read_json(KB / "snapshots.lock.json", {})
    today = kb_fetch.today_utc()
    report["no_previous"] = kb_fetch.record_changes(
        KB, lock, [c["id"] for c in report["changed_sources"]], [p["url"] for p in report["new_pages"]],
        [p["url"] for p in report["removed_pages"]], today)
    snap = KB / "snapshots"
    for sid, body in bodies.items():
        atomic_write(snap / f"{sid}.md", body)
    for sid, body in restore.items():
        atomic_write(snap / f"{sid}.md", body)
    report["restored_snapshots"] = sorted(restore)
    if urls_now:
        index_lock = read_json(KB / "index.lock.json", {})
        index_lock.update(urls_now)
        write_json(KB / "index.lock.json", index_lock)
    if bodies:
        for sid, body in bodies.items():
            lock[sid] = kb_fetch.lock_entry(sources[sid], body, today)
        write_json(KB / "snapshots.lock.json", lock)


def render(report: dict) -> str:
    nc = report["not_compared"]
    out = [f"fetch dates (UTC) in the lock: oldest {report['lock_oldest']}, newest {report['lock_newest']}",
           f"changed={len(report['changed_sources'])} unchanged={len(report['unchanged'])} failed={len(report['failed'])} "
           f"new_pages={len(report['new_pages'])} removed_pages={len(report['removed_pages'])} "
           f"pending={len(report['pending']['sources'])}+{len(report['pending']['new_pages'])}+{len(report['pending']['removed_pages'])}"]
    for c in report["changed_sources"]:
        pin = f"; in core/harness: {', '.join(c['core_or_harness_ids'])}" if c["core_or_harness_ids"] else ""
        out.append(f"  + {c['id']}{' (no lock entry)' if c['new'] else ''}: {c['claims']} claims depend on it{pin}")
    for p in report["pending"]["sources"]:
        pin = f"; in core/harness: {', '.join(p['core_or_harness_ids'])}" if p["core_or_harness_ids"] else ""
        out.append(f"  * pending since {p['since']}: {p['id']}: {p['claims']} claims not re-reviewed{pin}")
    for f in report["failed"]:
        out.append(f"  ! {f['id']}: {f['error']}")
    for index in report["no_index_baseline"]:
        out.append(f"  ? no index baseline for {index}; --apply records one")
    for sid in report["snapshot_mismatch"]:
        out.append(f"  ? local snapshot of {sid} differs from the lock; --apply restores it")
    for label, items, mark in (("new pages", report["new_pages"], "+"), ("removed pages", report["removed_pages"], "-"),
                               ("pending new pages", report["pending"]["new_pages"], "*"),
                               ("pending removed pages", report["pending"]["removed_pages"], "*")):
        for p in items[:SHOW]:
            out.append(f"  {mark} {p['url']}" + (f" (pending since {p['since']})" if "since" in p else ""))
        if len(items) > SHOW:
            out.append(f"  ... {len(items) - SHOW} more {label}; see --json")
    if nc["sources"]:
        out.append(f"not compared: {nc['sources']} bundled or local sources, {nc['claims']} claims that rest on them "
                   f"(needs --bundled-dir); the result above covers the sources with a url")
    if report["restored_snapshots"]:
        out.append(f"restored {len(report['restored_snapshots'])} local snapshots that were missing or differed from the lock")
    if report["no_previous"]:
        out.append(f"no previous snapshot to diff against: {', '.join(report['no_previous'])}; read those sources whole")
    if report["unreadable_claim_lines"]:
        out.append(f"{report['unreadable_claim_lines']} claim lines could not be read: impact counts are low")
    if report["incomplete"]:
        out.append("incomplete: " + "; ".join(report["incomplete"]))
    return "\n".join(out)


def review(items: str) -> int:
    """--reviewed: take items off pending, once the gate and the second reader have passed."""
    problem = clone_problem()
    if problem:
        print(f"refusing --reviewed: {problem}", file=sys.stderr)
        return 2
    pending = kb_fetch.read_pending(KB)
    if items.strip() == "all":
        wanted = [k for part in pending.values() for k in part]
    else:
        wanted = [i.strip() for i in items.split(",") if i.strip()]
        unknown = [i for i in wanted if not any(i in pending[k] for k in pending)]
        if unknown or not wanted:
            print(f"not pending: {', '.join(unknown) or '(nothing given)'}", file=sys.stderr)
            return 2
    gate = kb_gate.run(KB)
    if gate["errors"]:
        print(f"refusing --reviewed: the gate reports {len(gate['errors'])} errors, the first being: {gate['errors'][0]}. "
              "Fix them and run `python scripts/kb_gate.py` until it exits 0.", file=sys.stderr)
        return 2
    no_snapshot = sorted(s for s in wanted if s in pending["sources"] and not (KB / "snapshots" / f"{s}.md").exists())
    if no_snapshot:
        print(f"refusing --reviewed: no snapshot for {', '.join(no_snapshot)}, so the gate did not check their claims. "
              "Fetch them (`python scripts/kb_update.py --apply`, with --bundled-dir for bundled sources) and run the gate.",
              file=sys.stderr)
        return 2
    for key in pending:
        for i in wanted:
            pending[key].pop(i, None)
    write_json(KB / "pending.json", pending)
    print(f"pending left: {sum(len(v) for v in pending.values())}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Say what changed in the documentation since the last update, and what it affects. Exit codes: 0 compared "
                    "completely, nothing changed or pending; 1 nothing could be compared; 2 misuse; 3 there is work; "
                    "4 nothing changed but the comparison was incomplete.",
        epilog="Each request has a timeout of %d s and at most %d bytes; an index that parses into no urls, or fewer than half "
               "of the baseline, is not accepted as the new baseline." % (kb_fetch.TIMEOUT, kb_fetch.MAX_BYTES))
    ap.add_argument("--json", action="store_true", help="print the report as JSON (schema_version 1) instead of text")
    ap.add_argument("--out", default="", help="also write the JSON report to this file; it must be outside the plugin directory")
    ap.add_argument("--apply", action="store_true",
                    help="write changed snapshots, pending.json and the locks; working clone only, nothing applied if a source failed")
    ap.add_argument("--partial", action="store_true", help="with --apply, apply what downloaded even if a source failed")
    ap.add_argument("--reviewed", default="",
                    help="comma-separated source ids or page urls, or 'all': take them off pending; runs the gate first; "
                         "takes no other option")
    ap.add_argument("--only", default="", help="comma-separated source ids to compare; the indexes are then not checked")
    ap.add_argument("--bundled-dir", default="", help="claude-api skill directory: also compare `bundled` and `path` sources")
    ap.add_argument("--max-seconds", type=int, default=None,
                    help=f"time budget for all downloads, in-flight ones included (default {MAX_SECONDS}); sources not finished in time are reported as failed")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.reviewed:
        ignored = [flag for flag, value in (("--apply", args.apply), ("--partial", args.partial), ("--json", args.json),
                                            ("--out", args.out), ("--only", args.only), ("--bundled-dir", args.bundled_dir),
                                            ("--max-seconds", args.max_seconds is not None)) if value]
        if ignored:
            print(f"--reviewed takes no other option (got {', '.join(ignored)}); it is its own step", file=sys.stderr)
            return 2
        return review(args.reviewed)
    if args.partial and not args.apply:
        print("--partial only means something with --apply", file=sys.stderr)
        return 2
    if args.apply:
        problem = clone_problem()
        if problem:
            print(f"refusing --apply: {problem}", file=sys.stderr)
            return 2
    known = {s["id"] for s in read_json(KB / "sources.json", [])}
    unknown = [i.strip() for i in args.only.split(",") if i.strip() and i.strip() not in known]
    if unknown:
        print(f"unknown source id in --only: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if args.out:
        try:
            pathlib.Path(args.out).resolve().relative_to(KB.parent.resolve())
        except ValueError:
            pass
        else:
            print(f"--out {args.out} is inside the plugin directory; write the report elsewhere", file=sys.stderr)
            return 2

    report, bodies, restore, urls_now = check(args)
    if not report["compared"] and not report["failed"]:
        print("nothing was compared: the selected sources are bundled or local files, which need --bundled-dir, "
              "or sources.json lists none", file=sys.stderr)
        return 2
    report["applied"] = False
    if args.apply and report["failed"] and not args.partial:
        print(f"nothing applied: {len(report['failed'])} sources failed to download; run again, or use --partial", file=sys.stderr)
    elif args.apply:
        apply(report, bodies, restore, urls_now)
        report["applied"] = True
    if args.out:
        atomic_write(pathlib.Path(args.out), (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    if report["applied"]:
        print("next: python scripts/kb_gate.py", file=sys.stderr if args.json else sys.stdout)
    return report["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
