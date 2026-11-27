#!/usr/bin/env python3
"""Say what changed in the documentation since the last update, and what it affects.

In:  kb/sources.json, kb/snapshots.lock.json, kb/index.lock.json ({index_url: [sorted urls]}),
     kb/pending.json, kb/claims/*.jsonl, kb/core.json, kb/harness.json. Downloads each source
     with a `url` and the two documentation indexes in INDEXES.
Out: a report (or with --json, a JSON object): lock_oldest and lock_newest (the fetch dates of
     the snapshots in the lock, not review dates), changed_sources [{id, url, claims,
     core_or_harness_ids, new}], pending {sources, new_pages, removed_pages}, unchanged, failed
     [{id, erro}], not_checked [{id, motivo}], not_compared {sources, claims}, new_pages,
     removed_pages, no_index_baseline, snapshot_mismatch, unreadable_claim_lines, incomplete, exit.
     --out FILE also writes that JSON; FILE must be outside the plugin directory.
Fails: exit 0 the declared scope was compared completely and nothing changed or is pending;
       3 there is work: a changed source, a new or removed page, or a pending item;
       4 nothing changed was seen but the comparison was incomplete (a source or index failed,
         an index has no baseline, a local snapshot differs from the lock, a claim line was unreadable);
       1 nothing could be compared; 2 misuse: --apply outside a working clone (no .git, a plugin
       cache, or an unwritable kb/), an unknown --only id, --out inside the plugin, --reviewed
       with an item that is not pending. Failed sources keep their lock entry.

Two baselines. The lock says what was downloaded; kb/pending.json says what was downloaded but
not yet re-read. --apply writes snapshots and locks and adds every changed source and every new
or removed page to pending, which accumulates until `--reviewed ID[,ID...]|all` removes items
(call it only after the gate and the second reader). So an update that stops halfway keeps
flagging its claims: the check reports pending items as work even when today's bytes match.
Before overwriting a snapshot, --apply copies the previous one to kb/snapshots-prev/<id>.md
(kept from the first change that was not yet reviewed), so the re-reading has a diff.

Modes:
  default   reads the plugin and writes nothing inside it, so it runs from an installed copy that
            is read-only and has no kb/snapshots/. Run it as `python -B` so that no bytecode is
            written either; the script also sets that flag itself before importing kb_fetch.
  --apply   for a working clone only (kb/ writable, .git present, path not under plugins/cache).
            Writes the changed snapshots (and restores a missing or altered snapshot of an
            unchanged source), then pending.json, then the locks, each file by temporary file and
            os.replace. Applies nothing when a source failed, unless --partial. Does not run the
            gate: it prints the command to run next.

Usage: kb_update.py [--json] [--out FILE] [--apply [--partial]] [--only ID[,ID...]] [--bundled-dir DIR]
       kb_update.py --reviewed ID[,ID...]|all
  --only ID,...      limit the sources, as in kb_fetch.py; the indexes and index pending are then out of scope.
  --bundled-dir DIR  check `bundled` and `path` sources too. Without it they are counted in not_compared
                     and do not change the exit code: the declared scope is then the sources with a url.
  --reviewed ...     take items (source ids or page URLs) off pending; needs a working clone.

Network: GET requests only, to the hosts of the urls in kb/sources.json and of INDEXES, with the fixed
User-Agent of kb_fetch and a timeout per request. No review data, claim, setup or local path is sent;
the host still sees what any connection shows, such as the IP address. Reading a `bundled` or `path`
file is local and sends nothing.
Known limits: two updates run at once are not locked against each other; an HTML source is hashed
after its text is extracted, so a changed link target under identical text hashes identically.
Stdlib only.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # before kb_fetch is imported: a check must not leave scripts/__pycache__

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import pathlib
import re
import tempfile
import urllib.error

import kb_fetch

ROOT = pathlib.Path(__file__).resolve().parent.parent
KB = ROOT / "kb"
INDEXES = ("https://platform.claude.com/llms.txt", "https://code.claude.com/docs/llms.txt")
NET_ERRORS = (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException, ValueError)
_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
SHOW = 40


def read_json(path: pathlib.Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def atomic_write(path: pathlib.Path, data: bytes) -> None:
    """A temporary file in the same directory, then os.replace: the target is the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: pathlib.Path, data) -> None:
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


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


def read_pending() -> dict:
    pending = read_json(KB / "pending.json", {})
    return {k: dict(pending.get(k, {})) for k in ("sources", "new_pages", "removed_pages")}


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def check(args) -> tuple[dict, dict, dict, dict]:
    """Compare the outside with the locks. Returns (report, changed bodies, bodies to restore, index url lists)."""
    sources = read_json(KB / "sources.json", [])
    lock = read_json(KB / "snapshots.lock.json", {})
    index_lock = read_json(KB / "index.lock.json", {})
    only = {s for s in args.only.split(",") if s}
    cited, unreadable = claim_counts()
    pinned = pinned_ids()
    fetched_on = sorted(v["fetched"] for v in lock.values() if v.get("fetched"))
    report = {"lock_oldest": fetched_on[0] if fetched_on else None, "lock_newest": fetched_on[-1] if fetched_on else None,
              "changed_sources": [], "pending": {"sources": [], "new_pages": [], "removed_pages": []},
              "unchanged": [], "failed": [], "not_checked": [], "not_compared": {"sources": 0, "claims": 0},
              "new_pages": [], "removed_pages": [], "no_index_baseline": [], "snapshot_mismatch": [],
              "unreadable_claim_lines": unreadable, "incomplete": []}
    bodies: dict[str, bytes] = {}
    restore: dict[str, bytes] = {}
    compared = 0

    for src in sources:
        sid = src["id"]
        if only and sid not in only:
            continue
        if "url" not in src and not args.bundled_dir:
            report["not_checked"].append({"id": sid, "motivo": "bundled or local file; needs --bundled-dir"})
            report["not_compared"]["sources"] += 1
            report["not_compared"]["claims"] += len(cited.get(sid, []))
            continue
        if "url" not in src and "bundled" not in src and "path" not in src:
            report["not_checked"].append({"id": sid, "motivo": "no url, path or bundled in sources.json"})
            continue
        try:
            body = kb_fetch.read_source(src, args.bundled_dir)
        except NET_ERRORS as exc:
            report["failed"].append({"id": sid, "erro": str(exc)})
            continue
        compared += 1
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
        report["changed_sources"].append({"id": sid, "url": src.get("url") or src.get("path") or f"bundled:{src['bundled']}",
                                          "claims": len(ids), "core_or_harness_ids": sorted(set(ids) & pinned),
                                          "new": sid not in lock})

    urls_now: dict[str, list[str]] = {}
    for index in () if only else INDEXES:
        try:
            urls = index_urls(kb_fetch.http_get(index))
            before = index_lock.get(index)
            if not urls or (before and len(urls) * 2 < len(before)):
                raise ValueError(f"index parsed into {len(urls)} urls (baseline {len(before or [])}); response not accepted")
        except NET_ERRORS as exc:
            report["failed"].append({"id": index, "erro": str(exc)})
            continue
        urls_now[index] = urls
        if before is None:
            report["no_index_baseline"].append(index)
            continue
        compared += 1
        report["new_pages"] += [{"index": index, "url": u} for u in sorted(set(urls) - set(before))]
        report["removed_pages"] += [{"index": index, "url": u} for u in sorted(set(before) - set(urls))]

    pending = read_pending()
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
    report["exit"] = 1 if report["failed"] and not compared else 3 if work else 4 if report["incomplete"] else 0
    return report, bodies, restore, urls_now


def apply(report: dict, bodies: dict, restore: dict, urls_now: dict) -> None:
    """Order matters: pending first, so a run cut short still flags what it changed; the lock last."""
    sources = {s["id"]: s for s in read_json(KB / "sources.json", [])}
    lock = read_json(KB / "snapshots.lock.json", {})
    pending = read_pending()
    already = set(pending["sources"])
    today = dt.date.today().isoformat()
    for c in report["changed_sources"]:
        pending["sources"].setdefault(c["id"], today)
    for key in ("new_pages", "removed_pages"):
        for p in report[key]:
            pending[key].setdefault(p["url"], today)
    write_json(KB / "pending.json", pending)

    snap, prev = KB / "snapshots", KB / "snapshots-prev"
    for sid, body in bodies.items():
        old = snap / f"{sid}.md"
        # A source already pending keeps the older copy: the re-reading diffs against what was last reviewed.
        if old.exists() and (sid not in already or not (prev / f"{sid}.md").exists()):
            atomic_write(prev / f"{sid}.md", old.read_bytes())
        atomic_write(old, body)
    for sid, body in restore.items():
        atomic_write(snap / f"{sid}.md", body)
    report["restored_snapshots"] = sorted(restore)

    if urls_now:
        index_lock = read_json(KB / "index.lock.json", {})
        index_lock.update(urls_now)
        write_json(KB / "index.lock.json", index_lock)
    if bodies:
        for sid, body in bodies.items():
            src = sources[sid]
            lock[sid] = {"sha256": sha(body), "bytes": len(body), "fetched": today,
                         "source": src.get("url") or src.get("path") or f"bundled:{src['bundled']}"}
        write_json(KB / "snapshots.lock.json", lock)


def render(report: dict) -> str:
    nc = report["not_compared"]
    out = [f"fetch dates in the lock: oldest {report['lock_oldest']}, newest {report['lock_newest']}",
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
        out.append(f"  ! {f['id']}: {f['erro']}")
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
    pending = read_pending()
    if items.strip() == "all":
        pending = {k: {} for k in pending}
    else:
        wanted = [i for i in items.split(",") if i]
        unknown = [i for i in wanted if not any(i in pending[k] for k in pending)]
        if unknown or not wanted:
            print(f"not pending: {', '.join(unknown) or '(nothing given)'}", file=sys.stderr)
            return 2
        for i in wanted:
            for k in pending:
                pending[k].pop(i, None)
    write_json(KB / "pending.json", pending)
    print(f"pending left: {sum(len(v) for v in pending.values())}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--partial", action="store_true", help="with --apply, apply what downloaded even if a source failed")
    ap.add_argument("--reviewed", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--bundled-dir", default="")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.reviewed:
        if args.apply:
            print("--reviewed and --apply are separate steps", file=sys.stderr)
            return 2
        return review(args.reviewed)
    if args.apply:
        problem = clone_problem()
        if problem:
            print(f"refusing --apply: {problem}", file=sys.stderr)
            return 2
    known = {s["id"] for s in read_json(KB / "sources.json", [])}
    unknown = [i for i in args.only.split(",") if i and i not in known]
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
