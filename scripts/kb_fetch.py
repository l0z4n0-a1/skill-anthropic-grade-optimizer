#!/usr/bin/env python3
"""Fetch the knowledge-base sources listed in kb/sources.json into kb/snapshots/.

For bootstrap and recovery. The routine refresh is `kb_update.py --apply`, which also
reports what changed; both record a changed source in kb/pending.json the same way.

In:  kb/sources.json  -> [{"id", "url" | "path" | "bundled", "tier", "topic"}]
Out: kb/snapshots/<id>.md  (raw text, never committed) and kb/snapshots.lock.json
     ({id: {sha256, bytes, fetched, source}}; `fetched` is a UTC date), which is committed so a
     later run can tell which sources changed. When a source that already had a lock entry
     downloads with a different hash, its id goes into kb/pending.json ({"sources": {id: date},
     "new_pages": {url: date}, "removed_pages": {url: date}}; dates in UTC) until
     `kb_update.py --reviewed` releases it, and the previous snapshot is kept in
     kb/snapshots-prev/<id>.md if the local file existed and matched the lock. A source with
     no lock entry is new and is not pending.
     A local snapshot whose hash differs from the lock is rewritten even if the remote still
     matches the lock; a source whose bytes are unchanged but whose locator in sources.json is not the
     one the lock records gets its lock entry rewritten (it is not pending: nothing changed to read).
     A body shorter than its advertised Content-Length is a failed source, never a snapshot. Writes are by temporary file and os.replace; every download happens
     before anything is written, so a failure while downloading leaves the files as they were.
Fails: exit 0 every selected source was read; 1 some source could not be read (the others are
       written, the failed ones keep their lock entry) or --list could not read its URL;
       2 misuse: an unknown --only id, a missing kb/sources.json, or bad arguments.

Usage: kb_fetch.py [--only ID[,ID...]] [--bundled-dir DIR] [--list URL]
  --only ID,...      fetch only these source ids.
  --bundled-dir DIR  where the claude-api skill bundled with Claude Code is, for sources marked `bundled`.
  --list URL         print the URL's body to stdout (used to discover index pages) and write nothing.
A source `path` is read relative to the repository root, not to the current directory.
Network: GET only, a fixed generic User-Agent, a timeout of TIMEOUT seconds per request (kb_update.py
bounds it by its --max-seconds budget) and at most MAX_BYTES per response. A redirect is followed only to a host of the urls in kb/sources.json (for
--list, to the host of the URL given) and never from https to http. Nothing about the machine or the
review is sent, though a server sees the connection's address. Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html.parser
import http.client
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
KB = ROOT / "kb"
UA = "kb-fetch/1.0 (documentation snapshot)"
TIMEOUT = 60
MAX_BYTES = 5_000_000
CHUNK = 65536
NET_ERRORS = (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException, ValueError)


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class _PinnedRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to one of `hosts`, and never from https to http."""

    def __init__(self, hosts):
        self.hosts = {h.lower() for h in hosts}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if (target.hostname or "").lower() not in self.hosts or (
                urllib.parse.urlparse(req.full_url).scheme == "https" and target.scheme != "https"):
            raise urllib.error.URLError(f"redirect to {newurl} refused: only {', '.join(sorted(self.hosts))} are followed "
                                        "(add the host to kb/sources.json on purpose if it is right)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def hosts_of(urls) -> set[str]:
    return {h.lower() for h in (urllib.parse.urlparse(u).hostname for u in urls) if h}


def http_get(url: str, timeout: float = TIMEOUT, hosts=None, deadline=None) -> bytes:
    """GET `url`. `deadline` is an absolute time.monotonic() value: the request's timeout is cut to what is
    left of it, and a body still arriving when it passes is abandoned (TimeoutError). The socket timeout
    alone would restart with every chunk received. A body shorter than the Content-Length the server
    advertised is an error (the connection was cut), never a snapshot. The residual limit: a raw read
    already in progress when the deadline passes can still block for up to the request's own timeout."""
    if deadline is not None:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"time budget used up before {url} was requested")
        timeout = min(timeout, left)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/markdown, text/plain, */*"})
    opener = urllib.request.build_opener(_PinnedRedirect(hosts if hosts is not None else hosts_of([url])))
    chunks, size = [], 0
    with opener.open(req, timeout=timeout) as resp:
        read = getattr(resp, "read1", resp.read)  # read1 does one raw read, where read(n) waits for n bytes
        while True:
            chunk = read(CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise OSError(f"{url} is larger than {MAX_BYTES} bytes; refusing it")
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"time budget used up while {url} was downloading")
        headers = getattr(resp, "headers", None)
        try:
            advertised = int(headers.get("Content-Length")) if headers is not None and headers.get("Content-Length") else None
        except ValueError:
            advertised = None
        if advertised is not None and size < advertised:
            raise OSError(f"{url} ended after {size} of {advertised} bytes; the connection was cut, so the body is not used")
    return b"".join(chunks)


class _Text(html.parser.HTMLParser):
    """Keeps the readable text of an HTML page; drops script, style and chrome."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr", "br", "pre", "blockquote", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.out.append(data)


def html_to_text(body: bytes) -> bytes:
    parser = _Text()
    parser.feed(body.decode("utf-8", errors="replace"))
    text = re.sub(r"[ \t]+", " ", "".join(parser.out))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip().encode("utf-8")


def read_source(src: dict, bundled_dir: str, hosts=None, deadline=None) -> bytes:
    """A source is a URL, a local path (relative to the repository root), or a file of the claude-api skill bundled with Claude Code."""
    if "bundled" in src:
        if not bundled_dir:
            raise OSError("needs --bundled-dir (the claude-api skill directory of this Claude Code install)")
        return (pathlib.Path(bundled_dir) / src["bundled"]).read_bytes()
    if "path" in src:
        path = pathlib.Path(src["path"]).expanduser()
        return (path if path.is_absolute() else KB.parent / path).read_bytes()
    body = http_get(src["url"], hosts=hosts, deadline=deadline)
    if body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        return html_to_text(body)
    return body


def source_label(src: dict) -> str:
    return src.get("url") or src.get("path") or f"bundled:{src['bundled']}"


def lock_entry(src: dict, body: bytes, today: str) -> dict:
    return {"sha256": sha(body), "bytes": len(body), "fetched": today, "source": source_label(src)}


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


def read_json(path: pathlib.Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def read_pending(kb: pathlib.Path) -> dict:
    pending = read_json(kb / "pending.json", {})
    return {k: dict(pending.get(k, {})) for k in ("sources", "new_pages", "removed_pages")}


def record_changes(kb: pathlib.Path, lock: dict, changed: list[str], new_pages=(), removed_pages=(), today: str = "") -> list[str]:
    """The one place a download becomes pending work. Call it before the new snapshots are written.

    Marks in kb/pending.json every changed source that already had a lock entry (a source with
    none is new) and every new or removed page, then keeps each such source's previous snapshot in
    kb/snapshots-prev/ when the local file matches the lock. A source already pending is never given
    a new copy (the local file is then an unreviewed download): it keeps the older one, so the diff
    runs against what was last reviewed, or has none. Returns the ids with no usable
    previous snapshot: the reviewer must read those sources whole, not as a diff.
    """
    today = today or today_utc()
    pending = read_pending(kb)
    already = set(pending["sources"])
    tracked = [sid for sid in changed if sid in lock]
    no_previous = []
    # The previous copy of a new review cycle is settled before pending is published: a run cut short in between
    # must not leave a source pending with a copy from an older cycle, which a retry would then keep.
    for sid in tracked:
        prev, local = kb / "snapshots-prev" / f"{sid}.md", kb / "snapshots" / f"{sid}.md"
        if sid in already:
            # Pending: whatever is local now is an unreviewed download, never a baseline. Keep the older copy, or say there is none.
            if not prev.exists():
                no_previous.append(sid)
            continue
        if local.exists() and sha(local.read_bytes()) == lock[sid].get("sha256"):
            atomic_write(prev, local.read_bytes())
        else:
            prev.unlink(missing_ok=True)  # an older cycle's copy would be mistaken for this one's
            no_previous.append(sid)
    for sid in tracked:
        pending["sources"].setdefault(sid, today)
    for key, urls in (("new_pages", new_pages), ("removed_pages", removed_pages)):
        for url in urls:
            pending[key].setdefault(url, today)
    if tracked or new_pages or removed_pages:
        write_json(kb / "pending.json", pending)
    return no_previous


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch the knowledge-base sources into kb/snapshots/ (bootstrap and recovery; "
                                             "kb_update.py --apply is the routine refresh).")
    ap.add_argument("--only", default="", help="comma-separated source ids to fetch; an unknown id is an error (exit 2)")
    ap.add_argument("--list", default="", help="print this URL's body to stdout and write nothing")
    ap.add_argument("--bundled-dir", default="", help="directory of the claude-api skill bundled with Claude Code, for `bundled` sources")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        try:
            sys.stdout.write(http_get(args.list).decode("utf-8", errors="replace"))
        except NET_ERRORS as exc:
            print(f"could not read {args.list}: {exc}. Check the address and the network; "
                  "a redirect to another host is refused on purpose.", file=sys.stderr)
            return 1
        return 0

    try:
        sources = read_json(KB / "sources.json", None)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"cannot read {KB / 'sources.json'}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(sources, list):
        print(f"{KB / 'sources.json'} is missing or is not a list; run this from a checkout of the repository", file=sys.stderr)
        return 2
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = sorted(only - {s["id"] for s in sources})
    if unknown:
        print(f"unknown source id in --only: {', '.join(unknown)}", file=sys.stderr)
        return 2
    lock = read_json(KB / "snapshots.lock.json", {})
    snap = KB / "snapshots"
    hosts = hosts_of(s["url"] for s in sources if "url" in s)
    failed, changed, restore, relocated, same = [], {}, {}, {}, 0

    for src in sources:
        sid = src["id"]
        if only and sid not in only:
            continue
        try:
            body = read_source(src, args.bundled_dir, hosts)
        except NET_ERRORS as exc:
            failed.append(f"{sid}: {exc}")
            continue
        digest = sha(body)
        if digest == lock.get(sid, {}).get("sha256"):
            local = snap / f"{sid}.md"
            if lock[sid].get("source") != source_label(src):
                relocated[sid] = (src, body)  # same bytes from a new locator: the lock must say where they come from now
            if local.exists() and sha(local.read_bytes()) == digest:
                same += 1
            else:
                restore[sid] = body
            continue
        changed[sid] = (src, body)

    today = today_utc()
    no_previous = record_changes(KB, lock, list(changed), today=today)
    for sid, (src, body) in changed.items():
        atomic_write(snap / f"{sid}.md", body)
        lock[sid] = lock_entry(src, body, today)
    for sid, body in restore.items():
        atomic_write(snap / f"{sid}.md", body)
    for sid, (src, body) in relocated.items():
        lock[sid] = lock_entry(src, body, today)
    if changed or relocated:
        write_json(KB / "snapshots.lock.json", lock)

    print(f"changed={len(changed)} unchanged={same} restored={len(restore)} relocated={len(relocated)} failed={len(failed)}")
    for sid in changed:
        print(f"  + {sid} ({lock[sid]['bytes']} bytes)")
    for sid in relocated:
        print(f"  ~ {sid} unchanged, but its lock entry now names the locator sources.json gives")
    for sid in restore:
        print(f"  = {sid} rewritten: the local snapshot was missing or differed from the lock")
    for f in failed:
        print(f"  ! {f}")
    if no_previous:
        print(f"  no previous snapshot to diff against for {', '.join(no_previous)}: read those sources whole")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
