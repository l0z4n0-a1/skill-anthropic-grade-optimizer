#!/usr/bin/env python3
"""Fetch the knowledge-base sources listed in kb/sources.json into kb/snapshots/.

In:  kb/sources.json  -> [{"id", "url" | "path" | "bundled", "tier", "topic"}]
Out: kb/snapshots/<id>.md  (raw text, never committed) and kb/snapshots.lock.json
     ({id: {sha256, bytes, fetched, source}}), which is committed so a later run
     can tell which sources changed.
Fails: exit 1 if any source could not be read; the lock keeps the previous entry.

Usage: kb_fetch.py [--only ID[,ID...]] [--bundled-dir DIR] [--list URL]
  --bundled-dir DIR  where the claude-api skill bundled with Claude Code is, for sources marked `bundled`.
  --list URL         print the URL's body to stdout (used to discover index pages).
Stdlib only. Sends a generic User-Agent and nothing about the machine or user.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html.parser
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
KB = ROOT / "kb"
SNAP = KB / "snapshots"
LOCK = KB / "snapshots.lock.json"
UA = "kb-fetch/1.0 (documentation snapshot)"


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/markdown, text/plain, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


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


def read_source(src: dict, bundled_dir: str) -> bytes:
    """A source is a URL, a local path, or a file of the claude-api skill bundled with Claude Code."""
    if "bundled" in src:
        if not bundled_dir:
            raise OSError("needs --bundled-dir (the claude-api skill directory of this Claude Code install)")
        return (pathlib.Path(bundled_dir) / src["bundled"]).read_bytes()
    if "path" in src:
        return pathlib.Path(src["path"]).expanduser().read_bytes()
    body = http_get(src["url"])
    if body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        return html_to_text(body)
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--list", default="")
    ap.add_argument("--bundled-dir", default="")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        sys.stdout.write(http_get(args.list).decode("utf-8", errors="replace"))
        return 0

    sources = json.loads((KB / "sources.json").read_text(encoding="utf-8"))
    only = {s for s in args.only.split(",") if s}
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}
    SNAP.mkdir(parents=True, exist_ok=True)
    failed, changed, same = [], [], 0

    for src in sources:
        sid = src["id"]
        if only and sid not in only:
            continue
        try:
            body = read_source(src, args.bundled_dir)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            failed.append(f"{sid}: {exc}")
            continue
        digest = hashlib.sha256(body).hexdigest()
        if lock.get(sid, {}).get("sha256") == digest and (SNAP / f"{sid}.md").exists():
            same += 1
            continue
        (SNAP / f"{sid}.md").write_bytes(body)
        lock[sid] = {
            "sha256": digest,
            "bytes": len(body),
            "fetched": dt.date.today().isoformat(),
            "source": src.get("url") or src.get("path") or f"bundled:{src['bundled']}",
        }
        changed.append(sid)

    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"changed={len(changed)} unchanged={same} failed={len(failed)}")
    for c in changed:
        print(f"  + {c} ({lock[c]['bytes']} bytes)")
    for f in failed:
        print(f"  ! {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
