#!/usr/bin/env python3
"""Edit a Claude Code settings file without anyone reading it: hooks, permission rules and a few plain settings.

A settings file can hold secrets, so a model that edits one by opening it sees them. This script makes the same
edits and prints only the region it changed, never the rest of the file.

Usage: settings_edit.py <settings file> <operation> [options]
Operations (the only ones; --dry-run and --create apply to each):
  add-hook --event E [--matcher M] --command C [--timeout N] [--on-failure block]
        adds {type: command, command, timeout, onFailure} under hooks.E, in the group whose matcher is M (a new
        group when there is none). A hook with the same command already in that group is left as it is.
  remove-hook --event E --command-contains TEXT
        removes the one hook command under E that contains TEXT. Zero matches or more than one is a refusal
        (exit 2); the matching commands are listed so TEXT can be made more specific.
  set-hook-option --event E --command-contains TEXT [--on-failure block|default] [--timeout N]
        the same single-match rule; `default` removes onFailure. At least one of the two options is needed.
  add-permission --kind allow|ask|deny --rule RULE        no change when the rule is already there
  remove-permission --kind allow|ask|deny --rule RULE     no change when the rule is not there
  set --key K --value V
        only for the keys measure.py already exposes (SAFE_SETTINGS: plain configuration, never a secret).
        V is true or false, a whole number, or else text.
Common options: --dry-run prints what would change and writes nothing; --create makes the file as {} when it
does not exist (a missing file without --create is exit 2).

Output, for a real run and for --dry-run alike: the changed region only, as `change:`, `before:` and `after:`
(a hook entry with its matcher, a permission list, or a key with its old and new value), then what was done.
Nothing else from the file is printed, and an error message never repeats the file's content. The one exception
is the list of candidate commands when remove-hook or set-hook-option matches several hooks: a command is printed
there so TEXT can be made specific, and a command that embeds a secret would show it.

What is kept. The file is read as JSON and written back with its other keys, their order and their values
unchanged; whitespace is re-emitted in the file's own style (its indent, line endings, a byte-order mark and a
final newline are detected and kept), so a diff shows the edited region. Comments and a repeated key do not exist
in JSON and are not preserved. The write is atomic: a temporary file in the same folder, then os.replace, with the
file's existing mode kept (a new file is created 0600 where the system has modes; on Windows it takes its folder's ACL).
A symlink is followed and its target replaced.

The event name is checked only for shape (letters, starting upper-case), not against the list Claude Code
documents, so check its spelling: an event it does not know is ignored without error.

Exit codes:
  0  done, or nothing needed changing, or --dry-run
  1  the file could not be written (I/O error); it is left as it was
  2  refused or unusable: bad flag; the file is missing (no --create), is not valid JSON, is not a JSON object or
     has `hooks` or `permissions` in a shape this script does not edit; remove-hook or set-hook-option matched
     zero or several hooks; a key outside the allowlist. A message on stderr says why.

Stdlib only. Python 3.9+. No network.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backup import replace_atomic  # noqa: E402  (atomic write, shared with backup.py)
from measure import SAFE_SETTINGS, scalar  # noqa: E402  (the allowlist measure.py already exposes, not a copy of it)

EVENT_RE = re.compile(r"[A-Z][A-Za-z]*")
KINDS = ("allow", "ask", "deny")


class Refused(Exception):
    """The request or the file cannot be used. main() prints the message and exits 2."""


class WriteFailed(Exception):
    """The file could not be written. main() prints the message and exits 1."""


def show(value) -> str:
    return "(absent)" if value is None else json.dumps(value, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- reading and writing the file

class Document:
    def __init__(self, path: pathlib.Path, create: bool):
        self.path = path.resolve()
        self.bom, self.newline, self.indent, self.final_newline, self.mode = False, "\n", 2, True, 0o600
        self.created = False
        if self.path.is_dir():
            raise Refused(f"{path} is a folder, not a settings file")
        if not self.path.exists():
            if not create:
                raise Refused(f"{path} does not exist; add --create to make it")
            self.data, self.created = {}, True
            return
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise Refused(f"cannot read {path}: {type(exc).__name__}") from exc
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw.decode("utf-8-sig")
            data = json.loads(text)
        except UnicodeDecodeError as exc:
            raise Refused(f"{path} is not UTF-8 text") from exc
        except ValueError as exc:  # position only: the message never repeats the file's content
            where = f" (line {exc.lineno}, column {exc.colno})" if isinstance(exc, json.JSONDecodeError) else ""
            raise Refused(f"{path} is not valid JSON{where}; it was not changed") from exc
        if not isinstance(data, dict):
            raise Refused(f"{path} is JSON but not an object; it was not changed")
        self.data = data
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.final_newline = text.endswith("\n")
        indent = re.search(r"\n([ \t]+)\S", text)
        self.indent = None if "\n" not in text.strip() else ("\t" if indent and "\t" in indent.group(1) else len(indent.group(1)) if indent else 2)
        try:
            self.mode = self.path.stat().st_mode & 0o777
        except OSError:
            pass

    def render(self) -> bytes:
        text = json.dumps(self.data, indent=self.indent, ensure_ascii=False)
        text = text.replace("\n", self.newline) + (self.newline if self.final_newline else "")
        return (b"\xef\xbb\xbf" if self.bom else b"") + text.encode("utf-8")

    def save(self) -> None:
        try:
            replace_atomic(self.path, self.render(), self.mode)
        except OSError as exc:
            raise WriteFailed(f"could not write {self.path}: {type(exc).__name__}: {exc.strerror or exc}") from exc


# ---------------------------------------------------------------- operations: each returns (label, before, after)

# Hook events in the Claude Code hooks reference (snapshot of 2026-11-27). When kb/snapshots/cc-hooks.md is present,
# the events in its tables are added, so a knowledge-base update widens the list without a code change.
KNOWN_EVENTS = frozenset((
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion", "PreSkillShellCommand", "PreToolUse",
    "PermissionRequest", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "PostToolBatch", "Notification",
    "MessageDisplay", "SubagentStart", "SubagentStop", "SubagentHandback", "TaskCreated", "TaskCompleted", "Stop",
    "StopFailure", "TeammateIdle", "InstructionsLoaded", "ConfigChange", "CwdChanged", "DirectoryAdded", "FileChanged",
    "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact", "PreModelSwitch", "PostModelSwitch", "Elicitation",
    "ElicitationResult", "SessionEnd"))


def documented_events() -> frozenset:
    snap = pathlib.Path(__file__).resolve().parent.parent / "kb" / "snapshots" / "cc-hooks.md"
    try:
        found = re.findall(r"^\| `([A-Z][A-Za-z]+)` \|", snap.read_text(encoding="utf-8"), flags=re.M)
    except OSError:
        found = []
    return KNOWN_EVENTS | frozenset(found)


def event_groups(data: dict, event: str, create: bool = False):
    if not EVENT_RE.fullmatch(event):
        raise Refused(f"{event!r} is not an event name (letters, starting upper-case, like PreToolUse)")
    hooks = data.get("hooks")
    if hooks is None:
        if not create:
            return []
        hooks = data["hooks"] = {}
    if not isinstance(hooks, dict):
        raise Refused("`hooks` is not an object: this script does not edit that shape")
    groups = hooks.get(event)
    if groups is None:
        if not create:
            return []
        groups = hooks[event] = []
    if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks", []), list) for g in groups):
        raise Refused(f"`hooks.{event}` is not a list of {{matcher, hooks: [...]}} groups: this script does not edit that shape")
    return groups


def handlers(groups: list):
    """(group, handler) for every command hook in the groups."""
    return [(g, h) for g in groups for h in g.get("hooks", []) if isinstance(h, dict) and isinstance(h.get("command"), str)]


def entry(group: dict, handler: dict) -> dict:
    return ({"matcher": group["matcher"]} if "matcher" in group else {}) | {"hook": copy.deepcopy(handler)}


def unique_match(groups: list, event: str, text: str):
    if not text:
        raise Refused("--command-contains needs some text")
    found = [(g, h) for g, h in handlers(groups) if text in h["command"]]
    if len(found) == 1:
        return found[0]
    if not found:
        raise Refused(f"no hook command under {event} contains the text given; nothing was changed")
    listing = "\n".join(f"  {h['command']}" for _, h in found)
    raise Refused(f"{len(found)} hook commands under {event} contain the text given; make it match one. Candidates:\n{listing}")


def add_hook(data: dict, a):
    if not a.command.strip():
        raise Refused("--command needs a command")
    groups = event_groups(data, a.event, create=False)
    group = next((g for g in groups if g.get("matcher") == a.matcher), None) if a.matcher is not None else \
        next((g for g in groups if "matcher" not in g), None)
    if group is not None and any(h.get("command") == a.command for h in group.get("hooks", []) if isinstance(h, dict)):
        return f"hooks.{a.event} (already present)", None, None
    known = documented_events()
    if a.event not in known and not a.allow_unknown_event:
        # Claude Code ignores a hook under an event it does not know, without an error: refuse rather than write a dead hook.
        raise Refused(f"{a.event!r} is not a documented hook event; known: {', '.join(sorted(known))}. "
                      "If your Claude Code version documents it, pass --allow-unknown-event")
    hook = {"type": "command", "command": a.command}
    if a.timeout is not None:
        hook["timeout"] = a.timeout
    if a.on_failure:
        hook["onFailure"] = a.on_failure
    groups = event_groups(data, a.event, create=True)
    if group is None:
        group = ({"matcher": a.matcher} if a.matcher is not None else {}) | {"hooks": []}
        groups.append(group)
    group.setdefault("hooks", []).append(hook)
    return f"hooks.{a.event} (hook added)", None, entry(group, hook)


def remove_hook(data: dict, a):
    groups = event_groups(data, a.event)
    group, hook = unique_match(groups, a.event, a.command_contains)
    before = entry(group, hook)
    group["hooks"].remove(hook)
    if not group["hooks"]:
        groups.remove(group)
    if not groups:
        del data["hooks"][a.event]
    return f"hooks.{a.event} (hook removed)", before, None


def set_hook_option(data: dict, a):
    if a.on_failure is None and a.timeout is None:
        raise Refused("give --on-failure, --timeout or both")
    group, hook = unique_match(event_groups(data, a.event), a.event, a.command_contains)
    before = entry(group, hook)
    if a.on_failure == "block":
        hook["onFailure"] = "block"
    elif a.on_failure == "default":
        hook.pop("onFailure", None)
    if a.timeout is not None:
        hook["timeout"] = a.timeout
    after = entry(group, hook)
    if after == before:
        return f"hooks.{a.event} (options already so)", None, None
    return f"hooks.{a.event} (hook options)", before, after


def permission_list(data: dict, kind: str, create: bool):
    perms = data.get("permissions")
    if perms is None:
        if not create:
            return None
        perms = data["permissions"] = {}
    if not isinstance(perms, dict):
        raise Refused("`permissions` is not an object: this script does not edit that shape")
    rules = perms.get(kind)
    if rules is None:
        if not create:
            return None
        rules = perms[kind] = []
    if not isinstance(rules, list):
        raise Refused(f"`permissions.{kind}` is not a list: this script does not edit that shape")
    return rules


def add_permission(data: dict, a):
    if not a.rule.strip():
        raise Refused("--rule needs a rule")
    existing = permission_list(data, a.kind, create=False)
    if existing is not None and a.rule in existing:
        return f"permissions.{a.kind} (already present)", None, None
    before = None if existing is None else list(existing)
    rules = permission_list(data, a.kind, create=True)
    rules.append(a.rule)
    return f"permissions.{a.kind} (rule added)", before, list(rules)


def remove_permission(data: dict, a):
    rules = permission_list(data, a.kind, create=False)
    if rules is None or a.rule not in rules:
        return f"permissions.{a.kind} (rule not present)", None, None
    before = list(rules)
    rules.remove(a.rule)
    return f"permissions.{a.kind} (rule removed)", before, list(rules)


def set_key(data: dict, a):
    if a.key not in SAFE_SETTINGS:
        raise Refused(f"`{a.key}` is not a key this script sets; it sets only: {', '.join(sorted(SAFE_SETTINGS))}")
    try:
        parsed = json.loads(a.value)
    except ValueError:
        parsed = a.value
    value = parsed if isinstance(parsed, (bool, int)) else a.value
    if a.key in data and data[a.key] == value and type(data[a.key]) is type(value):
        return f"{a.key} (already set)", None, None
    old = scalar(data[a.key]) if a.key in data else None
    data[a.key] = value
    return f"{a.key} (set)", old, value


OPERATIONS = {"add-hook": add_hook, "remove-hook": remove_hook, "set-hook-option": set_hook_option,
              "add-permission": add_permission, "remove-permission": remove_permission, "set": set_key}


# ---------------------------------------------------------------- command line

def positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("a whole number") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("a whole number above 0")
    return value


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="settings_edit.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=(__doc__ or "").split("\n\n")[0],
                                 epilog="Exit codes: 0 done or nothing to change, 1 write failed, 2 refused or unusable input.")
    ap.add_argument("file", metavar="SETTINGS_FILE")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="print what would change and write nothing")
    common.add_argument("--create", action="store_true", help="create the file as {} when it does not exist")
    sub = ap.add_subparsers(dest="operation", required=True, metavar="OPERATION")

    def op(name: str, help_: str):
        return sub.add_parser(name, parents=[common], help=help_)

    p = op("add-hook", "add a command hook")
    p.add_argument("--event", required=True)
    p.add_argument("--matcher", default=None)
    p.add_argument("--command", required=True)
    p.add_argument("--timeout", type=positive, default=None)
    p.add_argument("--on-failure", choices=["block"], default=None)
    p.add_argument("--allow-unknown-event", action="store_true",
                   help="accept an event name not in the documented list (for an event newer than this plugin)")
    p = op("remove-hook", "remove the one hook command containing TEXT")
    p.add_argument("--event", required=True)
    p.add_argument("--command-contains", required=True, metavar="TEXT")
    p = op("set-hook-option", "set or clear onFailure, or set the timeout, of the one hook containing TEXT")
    p.add_argument("--event", required=True)
    p.add_argument("--command-contains", required=True, metavar="TEXT")
    p.add_argument("--on-failure", choices=["block", "default"], default=None)
    p.add_argument("--timeout", type=positive, default=None)
    for name in ("add-permission", "remove-permission"):
        p = op(name, f"{name.split('-')[0]} a permission rule")
        p.add_argument("--kind", required=True, choices=KINDS)
        p.add_argument("--rule", required=True)
    p = op("set", "set a plain configuration key from the allowlist")
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)
    return ap


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        doc = Document(pathlib.Path(args.file), args.create)
        label, before, after = OPERATIONS[args.operation](doc.data, args)
        changed = before is not None or after is not None
        print(f"change: {label}")
        if changed:
            print(f"before: {show(before)}")
            print(f"after: {show(after)}")
        if not changed:
            print("nothing to change")
        elif args.dry_run:
            print("dry run: nothing written")
        else:
            doc.save()
            print(f"written: {doc.path}")
        return 0
    except Refused as exc:
        print(f"settings_edit.py: {exc}", file=sys.stderr)
        return 2
    except WriteFailed as exc:
        print(f"settings_edit.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
