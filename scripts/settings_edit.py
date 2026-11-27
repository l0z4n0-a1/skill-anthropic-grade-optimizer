#!/usr/bin/env python3
"""Edit a Claude Code settings file without anyone reading it: hooks, permission rules and a few plain settings.

A settings file can hold secrets, so a model that edits one by opening it sees them. This script makes the same
edits and prints only the region it changed, with hook commands masked, never the rest of the file.

Usage: settings_edit.py <settings file> <operation> [options]
Operations (the only ones; the common options below apply to each):
  add-hook --event E [--matcher M] --command C [--timeout N] [--on-failure block] [--allow-unknown-event]
        adds {type: command, command, timeout, onFailure} under hooks.E, in the group whose matcher is M (a new
        group when there is none). A hook with the same command already in that group is left as it is. An event
        that is not in the documented list (built in, widened by kb/snapshots/cc-hooks.md when present) is refused,
        because Claude Code ignores a hook under an unknown event without an error; --allow-unknown-event accepts it.
  remove-hook --event E (--command-contains TEXT | --index N)
        removes one command hook under E. TEXT must match exactly one command, or --index picks one; zero or
        several matches is a refusal (exit 2) that lists the candidates as index, event, matcher and masked command.
        --index N is the position among the event's command hooks, in file order; it removes exactly that one even
        when another hook is identical to it.
  set-hook-option --event E (--command-contains TEXT | --index N) [--on-failure block|default] [--timeout N]
        the same selection; `default` removes onFailure. At least one of the two options is needed.
  add-permission --kind allow|ask|deny --rule RULE        no change when the rule is already there
  remove-permission --kind allow|ask|deny --rule RULE     no change when the rule is not there
  set --key K --value V
        only for the keys measure.py already exposes (SAFE_SETTINGS: plain configuration, never a secret).
        V is true or false, a whole number, or else text.
Common options:
  --dry-run             print what would change and write nothing
  --create              make the file as {} when it does not exist (a missing file without it is exit 2)
  --expect-sha256 H     refuse (exit 2) unless the file's sha256 is H now ("absent" for a file that does not exist
                        yet): bind a write to the file a dry run showed. The hash is checked again just before
                        the file is replaced.
  --follow-links        accept a path that reaches the file through a symlink or junction (see below)

Output, for a real run and for --dry-run alike: `target:` (the canonical path it will write), `sha256:` of the
file as it is now, then `change:` with `before:` and `after:` showing the changed region only (one hook entry with
its matcher; for set-hook-option only the fields that change; a permission list; or a key with old and new value),
and `new sha256:` and what was done. Nothing else from the file is printed. A hook command or permission rule is
never printed as written, in any operation or refusal (candidate lists included): only the program name and the base
name of its first path-like argument, then "…" (`python guard.py …`, `Bash(git …)`), through measure.mask_command
and mask_rule, the same rule measure.py applies to its report. What is not named there is dropped, quoted or not: no
argument, header, URL or leading NAME=value assignment is ever shown. Other fields of a hook are listed by name only,
and a printed type, timeout or onFailure that is not a plain word or number shows as (other). An error message never
repeats the file's content.

What is kept. The file is read as JSON and written back with its other keys, their order and their values
unchanged; whitespace is re-emitted in the file's own style (its indent, line endings, a byte-order mark and a
final newline are detected and kept). A file that cannot be written back faithfully is refused, not rewritten: one
with a repeated key in any object (JSON keeps only the last), a number that overflows (1e400 would become the invalid
Infinity) or underflows to zero, or NaN or Infinity. Comments do not exist in JSON. The write is atomic: a temporary
file in the same folder, then os.replace, with the file's existing mode kept (a new file is created 0600 where the
system has modes). On Windows the replacement takes the folder's inherited access rules, not a per-file ACL the old
file had.

Links. The path given and every folder above it are checked: if reaching the file goes through a symlink or
junction that leads somewhere other than the path as given, the run is refused (exit 2) unless --follow-links;
`target:` always shows where the write would land.

An event name must have the shape of one (letters, starting upper-case) for every operation; add-hook also checks
it against the documented list, as above. remove-hook and set-hook-option do not, so a hook under a misspelled
event can still be found.

Exit codes:
  0  done, or nothing needed changing, or --dry-run
  1  the file could not be written (I/O error); it is left as it was
  2  refused or unusable: bad flag; the file is missing (no --create), is not valid JSON, cannot round-trip, is not
     a JSON object, or has `hooks` or `permissions` in a shape this script does not edit; the file differs from
     --expect-sha256 or changed while the edit was prepared; the path goes through a link (no --follow-links);
     remove-hook or set-hook-option matched zero or several hooks; a key outside the allowlist. A message on
     stderr says why.

Stdlib only. Python 3.9+. No network.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backup import replace_atomic  # noqa: E402  (atomic write, shared with backup.py)
from measure import SAFE_SETTINGS, mask_command, mask_rule, scalar  # noqa: E402  (what measure.py already exposes, not copies)

EVENT_RE = re.compile(r"[A-Z][A-Za-z]*")
KINDS = ("allow", "ask", "deny")
HANDLER_FIELDS = ("type", "command", "timeout", "onFailure")


class Refused(Exception):
    """The request or the file cannot be used. main() prints the message and exits 2."""


class WriteFailed(Exception):
    """The file could not be written. main() prints the message and exits 1."""


def show(value) -> str:
    return "(absent)" if value is None else json.dumps(value, indent=2, ensure_ascii=False)


def digest(data) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


def plain(value):
    """A value from the file as it may be printed: a number, a boolean, or a short plain word; anything else is hidden."""
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z_-]{0,19}", value) else "(other)"


# ---------------------------------------------------------------- reading and writing the file

def reject_constant(name):
    raise ValueError("non-finite number")


def parse_float(text: str) -> float:
    value = float(text)
    mantissa = re.split(r"[eE]", text)[0]
    if not math.isfinite(value) or (value == 0 and re.search(r"[1-9]", mantissa)):
        raise ValueError("number out of range")
    return value


def no_repeated_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("repeated key")
    return dict(pairs)


def check_links(given: pathlib.Path, follow: bool) -> pathlib.Path:
    """The canonical path to write. Refuses a route through a symlink or junction unless follow."""
    plain = pathlib.Path(os.path.abspath(given))
    real = pathlib.Path(os.path.realpath(given))
    if os.path.normcase(str(plain)) != os.path.normcase(str(real)) and not follow:
        raise Refused(f"{plain} reaches the file through a symlink or junction, which leads to {real}; "
                      "check that is the file you mean, then add --follow-links")
    return real


class Document:
    def __init__(self, path: pathlib.Path, create: bool, follow_links: bool = False):
        self.path = check_links(path, follow_links)
        self.bom, self.newline, self.indent, self.final_newline, self.mode = False, "\n", 2, True, 0o600
        self.created, self.raw = False, None
        if self.path.is_dir():
            raise Refused(f"{self.path} is a folder, not a settings file")
        if not self.path.exists():
            if not create:
                raise Refused(f"{self.path} does not exist; add --create to make it")
            self.data, self.created = {}, True
            return
        try:
            self.raw = raw = self.path.read_bytes()
        except OSError as exc:
            raise Refused(f"cannot read {self.path}: {type(exc).__name__}") from exc
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw.decode("utf-8-sig")
            data = json.loads(text, object_pairs_hook=no_repeated_keys, parse_float=parse_float, parse_constant=reject_constant)
        except UnicodeDecodeError as exc:
            raise Refused(f"{self.path} is not UTF-8 text") from exc
        except json.JSONDecodeError as exc:  # position only: the message never repeats the file's content
            raise Refused(f"{self.path} is not valid JSON (line {exc.lineno}, column {exc.colno}); it was not changed") from exc
        except (ValueError, RecursionError) as exc:
            raise Refused(f"{self.path} cannot be rewritten without changing it (a repeated key, a number out of range, "
                          "NaN or Infinity, or too deep); it was not changed") from exc
        if not isinstance(data, dict):
            raise Refused(f"{self.path} is JSON but not an object; it was not changed")
        self.data = data
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.final_newline = text.endswith("\n")
        indent = re.search(r"\n([ \t]+)\S", text)
        self.indent = None if "\n" not in text.strip() else ("\t" if indent and "\t" in indent.group(1) else len(indent.group(1)) if indent else 2)
        try:
            self.mode = self.path.stat().st_mode & 0o777
        except OSError:
            pass

    @property
    def sha256(self) -> str:
        return digest(self.raw)

    def render(self) -> bytes:
        text = json.dumps(self.data, indent=self.indent, ensure_ascii=False, allow_nan=False)
        text = text.replace("\n", self.newline) + (self.newline if self.final_newline else "")
        return (b"\xef\xbb\xbf" if self.bom else b"") + text.encode("utf-8")

    def save(self) -> None:
        try:  # the file must still be the one that was read: a change since would be overwritten
            now = self.path.read_bytes() if self.path.exists() else None
        except OSError as exc:
            raise WriteFailed(f"could not re-read {self.path}: {type(exc).__name__}") from exc
        if digest(now) != self.sha256:
            raise Refused(f"{self.path} changed while the edit was being prepared; nothing was written")
        try:
            replace_atomic(self.path, self.render(), self.mode)
        except OSError as exc:
            raise WriteFailed(f"could not write {self.path}: {type(exc).__name__}: {exc.strerror or exc}") from exc


# ---------------------------------------------------------------- operations: each returns (label, before, after), display-ready

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
    """[(index, group, handler)] for every command hook of the event, in file order. The index is what --index takes."""
    found = [(g, h) for g in groups for h in g.get("hooks", []) if isinstance(h, dict) and isinstance(h.get("command"), str)]
    return [(i, g, h) for i, (g, h) in enumerate(found)]


def matcher_of(group: dict) -> str:
    """A group's matcher as it may be printed: a short pattern of word characters, | . * : and -, else (other)."""
    value = group.get("matcher", "")
    return value if isinstance(value, str) and re.fullmatch(r"[\w|.*:-]{0,80}", value) else "(other)"


def view(event: str, group: dict, handler: dict, index=None) -> dict:
    """A hook as it is printed: event, matcher, the four fields it can carry with the command masked, other fields by name."""
    shown = {"event": event}
    if index is not None:
        shown["index"] = index
    if "matcher" in group:
        shown["matcher"] = matcher_of(group)
    for field in HANDLER_FIELDS:
        if field in handler:
            shown[field] = mask_command(handler[field]) if field == "command" else plain(handler[field])
    others = sorted(k for k in handler if k not in HANDLER_FIELDS)
    if others:
        shown["other_fields"] = others
    return shown


def candidates(groups: list, event: str, only=None) -> str:
    rows = [f"  [{i}] {event} matcher={matcher_of(g)!r} command: {mask_command(h['command'])}" if "matcher" in g else
            f"  [{i}] {event} matcher=(none) command: {mask_command(h['command'])}"
            for i, g, h in handlers(groups) if only is None or i in only]
    return "\n".join(rows) if rows else "  (no command hooks under this event)"


def pick(groups: list, event: str, text, index):
    """The one (group, handler) the request names, or a refusal that lists candidates."""
    if text is not None and not text:
        raise Refused("--command-contains needs some text")
    if text is None and index is None:
        raise Refused("give --command-contains TEXT or --index N")
    every = handlers(groups)
    if index is not None:
        if not 0 <= index < len(every):
            raise Refused(f"--index {index} is out of range for {event}; its command hooks are:\n{candidates(groups, event)}")
        _, group, hook = every[index]
        if text is not None and text not in hook["command"]:
            raise Refused(f"the hook at index {index} does not contain the text given; nothing was changed")
        return group, hook
    found = [(i, g, h) for i, g, h in every if text in h["command"]]
    if len(found) == 1:
        return found[0][1], found[0][2]
    if not found:
        raise Refused(f"no hook command under {event} contains the text given; nothing was changed. "
                      f"Its command hooks are:\n{candidates(groups, event)}")
    raise Refused(f"{len(found)} hook commands under {event} contain the text given; pick one with --index N. Candidates:\n"
                  f"{candidates(groups, event, {i for i, _, _ in found})}")


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
    return f"hooks.{a.event} (hook added)", None, view(a.event, group, hook)


def remove_hook(data: dict, a):
    groups = event_groups(data, a.event)
    group, hook = pick(groups, a.event, a.command_contains, a.index)
    before = view(a.event, group, hook)
    group["hooks"][:] = [h for h in group["hooks"] if h is not hook]  # by identity: an identical hook elsewhere stays
    if not group["hooks"]:
        groups[:] = [g for g in groups if g is not group]
    if not groups:
        del data["hooks"][a.event]
    return f"hooks.{a.event} (hook removed)", before, None


def set_hook_option(data: dict, a):
    if a.on_failure is None and a.timeout is None:
        raise Refused("give --on-failure, --timeout or both")
    group, hook = pick(event_groups(data, a.event), a.event, a.command_contains, a.index)
    old = {k: hook.get(k) for k in ("onFailure", "timeout")}
    if a.on_failure == "block":
        hook["onFailure"] = "block"
    elif a.on_failure == "default":
        hook.pop("onFailure", None)
    if a.timeout is not None:
        hook["timeout"] = a.timeout
    new = {k: hook.get(k) for k in ("onFailure", "timeout")}
    if new == old:
        return f"hooks.{a.event} (options already so)", None, None
    head = {"event": a.event} | ({"matcher": matcher_of(group)} if "matcher" in group else {})
    changed = [k for k in old if old[k] != new[k]]
    return (f"hooks.{a.event} (hook options)", head | {k: plain(old[k]) for k in changed}, head | {k: plain(new[k]) for k in changed})


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


def masked(rules) -> list:
    return [mask_rule(r) if isinstance(r, str) else f"({type(r).__name__})" for r in rules]


def add_permission(data: dict, a):
    if not a.rule.strip():
        raise Refused("--rule needs a rule")
    existing = permission_list(data, a.kind, create=False)
    if existing is not None and a.rule in existing:
        return f"permissions.{a.kind} (already present)", None, None
    before = None if existing is None else masked(existing)
    rules = permission_list(data, a.kind, create=True)
    rules.append(a.rule)
    return f"permissions.{a.kind} (rule added)", before, masked(rules)


def remove_permission(data: dict, a):
    rules = permission_list(data, a.kind, create=False)
    if rules is None or a.rule not in rules:
        return f"permissions.{a.kind} (rule not present)", None, None
    before = masked(rules)
    rules.remove(a.rule)
    return f"permissions.{a.kind} (rule removed)", before, masked(rules)


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


def index_number(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError("0 or more")
    return value


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="settings_edit.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=(__doc__ or "").split("\n\n")[0],
                                 epilog="Exit codes: 0 done or nothing to change, 1 write failed, 2 refused or unusable input.")
    ap.add_argument("file", metavar="SETTINGS_FILE")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="print what would change and write nothing")
    common.add_argument("--create", action="store_true", help="create the file as {} when it does not exist")
    common.add_argument("--expect-sha256", default=None, metavar="H", help="refuse unless the file's sha256 is H now (absent for no file)")
    common.add_argument("--follow-links", action="store_true", help="accept a path that goes through a symlink or junction")
    sub = ap.add_subparsers(dest="operation", required=True, metavar="OPERATION")

    def op(name: str, help_: str):
        return sub.add_parser(name, parents=[common], help=help_)

    def select(p):
        p.add_argument("--event", required=True)
        p.add_argument("--command-contains", default=None, metavar="TEXT")
        p.add_argument("--index", type=index_number, default=None, metavar="N", help="the index a refusal listed")

    p = op("add-hook", "add a command hook")
    p.add_argument("--event", required=True)
    p.add_argument("--matcher", default=None)
    p.add_argument("--command", required=True)
    p.add_argument("--timeout", type=positive, default=None)
    p.add_argument("--on-failure", choices=["block"], default=None)
    p.add_argument("--allow-unknown-event", action="store_true",
                   help="accept an event name not in the documented list (for an event newer than this plugin)")
    p = op("remove-hook", "remove the one hook command named by TEXT or --index")
    select(p)
    p = op("set-hook-option", "set or clear onFailure, or set the timeout, of the one hook named by TEXT or --index")
    select(p)
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
        doc = Document(pathlib.Path(args.file), args.create, args.follow_links)
        print(f"target: {doc.path}")
        print(f"sha256: {doc.sha256}")
        if args.expect_sha256 is not None and args.expect_sha256.strip().lower() != doc.sha256:
            raise Refused("the file's sha256 is not the one expected (it changed since the preview); nothing was changed. "
                          "Run again with --dry-run to see the current state")
        label, before, after = OPERATIONS[args.operation](doc.data, args)
        changed = before is not None or after is not None
        print(f"change: {label}")
        if not changed:
            print("nothing to change")
            return 0
        print(f"before: {show(before)}")
        print(f"after: {show(after)}")
        print(f"new sha256: {digest(doc.render())}")
        if args.dry_run:
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
