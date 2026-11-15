#!/usr/bin/env python3
"""Measure a Claude Code setup: what exists, when each piece loads, what it costs, how it is used.

This is the deterministic half of the review. It counts and lists; it does not judge.
Everything it reports is read from disk or computed from local session history,
and each estimate is labelled as one.

In:  --home     the user-level Claude Code directory (default: $CLAUDE_CONFIG_DIR, else ~/.claude)
     --project  a project directory (default: current directory)
     --days     how far back to read session history (default 30; 0 skips it)
     --out      where to write the full JSON (default: stdout summary only)
     --compare  an earlier JSON written with --out; also prints what changed since
     --piece    measure one skill or subagent file on its own, installed or not
Out: a JSON document (see `build()`), and a short text summary on stdout.
Fails: exit 2 if --home does not exist. A file that cannot be read or parsed is
       listed under `unreadable` and its content is left out of the figures.

Scope: pieces are those of the user level, the given project and enabled plugins.
Usage covers every project on this machine, because user-level pieces serve all
of them; an agent with no definition here (built in, or defined in another
project) is listed under `spawned_without_definition_here`. What the script
does not read is listed in the output under `not_measured`.

Privacy: reads local files only and makes no network call. It copies what a
review needs and nothing else: the values of a fixed list of frontmatter fields
and settings, hook definitions (event, matcher, command, timeout and a fixed
list of options), permission rules, and the names of servers, plugins, models,
tools, skills and agents. It never copies `env` values, MCP server arguments,
message text, or the contents of any frontmatter block outside the list. What it
copies, it copies as written: a secret typed into a description, a hook command
or a permission rule appears in the output, so treat the JSON like the files it
was read from.

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import re
import shlex
import sys

CHARS_PER_TOKEN = 4  # an estimating convention, not a fact about Claude Code; every figure from it is labelled an estimate
# Facts about Claude Code live in kb/harness.json, each tied to the claim that documents it.
_HARNESS = json.loads((pathlib.Path(__file__).resolve().parent.parent / "kb" / "harness.json").read_text(encoding="utf-8"))
LISTING_CAP = _HARNESS["skill_listing_cap_chars"]["value"]
IMPORT_DEPTH = _HARNESS["instruction_import_max_hops"]["value"]
LONG_FILE_LINES = _HARNESS["instruction_file_recommended_max_lines"]["value"]
CACHE_SHORT = _HARNESS["cache_lifetime_seconds_short"]["value"]
CACHE_LONG = _HARNESS["cache_lifetime_seconds_long"]["value"]

# Allowlists. A value is copied only when its key is named here; any other key is recorded by name.
SAFE_FIELDS = {"name", "description", "when_to_use", "model", "effort", "tools", "disallowedTools", "allowed-tools",
               "disable-model-invocation", "user-invocable", "context", "agent", "paths", "permissionMode", "maxTurns",
               "skills", "memory", "background", "isolation", "color", "argument-hint", "version", "license"}
SAFE_SETTINGS = {"model", "outputStyle", "effortLevel", "autoCompactWindow", "cleanupPeriodDays",
                 "disableBundledSkills", "alwaysThinkingEnabled", "autoMemoryEnabled"}
SAFE_HOOK_OPTIONS = {"onFailure", "async", "once", "continueOnBlock"}
TEXT_FIELDS = {"description", "when_to_use", "argument-hint"}  # prose; every other safe field is a scalar or a list
SKILL_STATES = {"on", "name-only", "user-invocable-only", "off"}
SCRIPT_EXT = r"(?:py|sh|js|mjs|cjs|ts|ps1|cmd|bat|rb|pl)"
MAX_VALUE = 2000  # longest frontmatter value kept
NAME_RE = re.compile(r"[\w.:@/+-]{1,80}")
STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def est_tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def num(value) -> int:
    """A token count, or 0 for anything that is not a plausible one."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**12 else 0


def clean_name(value) -> str:
    """A model, tool, skill or agent name from session history, or a placeholder when it is not name-shaped."""
    text = value if isinstance(value, str) else ""
    return text if NAME_RE.fullmatch(text) else "(unreadable name)"


def scalar(value):
    return value if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 200 else f"({type(value).__name__})"


def read(path: pathlib.Path, unreadable: list) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        unreadable.append(f"{path}: {type(exc).__name__}")
        return ""


def read_json(path: pathlib.Path, unreadable: list) -> dict:
    """A JSON object from disk, or {} with the reason recorded. A missing file is not an error."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        unreadable.append(f"{path}: {type(exc).__name__}")
        return {}
    if not isinstance(data, dict):
        unreadable.append(f"{path}: expected a JSON object, found {type(data).__name__}")
        return {}
    return data


def frontmatter(text: str):
    """Reads the frontmatter block. Returns (safe fields, names of other fields, body).

    The rule is structural: a line that starts in the first column begins a new
    top-level entry, whatever it looks like; an indented line belongs to the entry
    above it. Values are kept only for entries whose key is in SAFE_FIELDS, so a
    block under any other key (quoted, commented, oddly spaced) is never copied.
    Under a safe key, list items are kept; free continuation text is kept only for
    the prose fields, so a mapping nested under `tools:` or `skills:` is dropped.
    """
    if not text.startswith("---"):
        return {}, [], text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, [], text
    data, other, key = {}, [], None
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        item = line.strip()
        is_list_item = item.startswith("- ") and key is not None
        if not line[0].isspace() and not is_list_item:
            m = re.match(r"^([A-Za-z0-9_-]+):(?:\s+(.*))?$", line)
            if m and m.group(1) in SAFE_FIELDS:
                key, val = m.group(1), (m.group(2) or "").strip()
                if key not in TEXT_FIELDS:
                    val = re.sub(r"\s+#.*$", "", val)  # a trailing YAML comment
                    if val.startswith("{"):
                        val = "(mapping)"
                data[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
            else:
                key = None
                label = re.match(r"^[\"']?([A-Za-z][A-Za-z0-9_.-]{0,40})[\"']?\s*:", line)
                if label:
                    other.append(label.group(1))
        elif key and is_list_item:
            entry = item[2:].strip().strip("\"'")
            if key in TEXT_FIELDS or not re.search(r":\s|:$|^\{", entry):  # a list of mappings is not a list of names
                data[key] = f"{data[key]}, {entry}" if data[key] else entry
        elif key in TEXT_FIELDS:
            data[key] = (data[key] + " " + item).strip()
    return {k: v[:MAX_VALUE] for k, v in data.items()}, other, text[end + 4:]


# ---------------------------------------------------------------- pieces on disk

def instruction_files(home: pathlib.Path, project: pathlib.Path, unreadable: list) -> list:
    """Instruction files that load at session start, with the files they import.

    An AGENTS.md found on its own beside a CLAUDE.md is listed with
    `loads: "only if no CLAUDE.md is found"`, since by default Claude Code reads it
    only in that case. One that a CLAUDE.md imports loads with that file.
    """
    roots = [(home / "CLAUDE.md", "user")]
    for d in reversed([project, *project.parents]):
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md"):
            p = d / name
            if p != home / "CLAUDE.md":
                roots.append((p, "project" if d == project else "ancestor"))
    roots.sort(key=lambda r: r[0].name == "AGENTS.md")  # imports of AGENTS.md are met before the bare file
    out, seen = [], set()
    has_claude_md = any(p.is_file() and p.name != "AGENTS.md" and scope != "user" for p, scope in roots)

    def add(path: pathlib.Path, scope: str, via: str, depth: int) -> None:
        try:
            key = path.resolve()
        except OSError:
            return
        if key in seen or not path.is_file():
            return
        seen.add(key)
        text = read(path, unreadable)
        fallback = path.name == "AGENTS.md" and has_claude_md and not via
        out.append({"path": str(path), "scope": scope, "imported_by": via, "chars": len(text),
                    "lines": text.count("\n") + 1, "est_tokens": est_tokens(len(text)),
                    "loads": "only if no CLAUDE.md is found" if fallback else "session start"})
        if depth >= IMPORT_DEPTH or fallback:
            return
        body = re.sub(r"```.*?```", "", text, flags=re.S)
        for ref in re.findall(r"(?<![\w`@])@((?:~|\.{1,2})?[\w./\\-]*[\w-]\.[A-Za-z0-9]{1,8})(?![\w/])", body):
            target = pathlib.Path(os.path.expanduser(ref))
            if not target.is_absolute():
                target = path.parent / target
            add(target, scope, str(path), depth + 1)

    for path, scope in roots:
        add(path, scope, "", 0)
    return out


def settings_files(home: pathlib.Path, project: pathlib.Path, unreadable: list) -> list:
    """(scope, path, parsed object) for each settings file that exists, lowest precedence first."""
    found, seen = [], set()
    for label, path in (("user", home / "settings.json"), ("project", project / ".claude" / "settings.json"),
                        ("local", project / ".claude" / "settings.local.json")):
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        found.append((label, path, read_json(path, unreadable)))
    return found


def scopes(home: pathlib.Path, project: pathlib.Path, settings: list, unreadable: list) -> list:
    """(label, directory) for every place that can hold skills, agents, commands, rules, styles."""
    found = [("user", home)]
    if (project / ".claude").is_dir() and (project / ".claude").resolve() != home.resolve():
        found.append(("project", project / ".claude"))
    enabled = set()
    for _, _, data in settings:
        enabled |= {k for k, v in as_dict(data.get("enabledPlugins")).items() if v}
    installed = read_json(home / "plugins" / "installed_plugins.json", unreadable)
    for key, entries in as_dict(installed.get("plugins")).items():
        if key not in enabled:
            continue
        for entry in as_list(entries) or [entries]:
            where = as_dict(entry).get("installPath")
            if isinstance(where, str) and where and pathlib.Path(where).is_dir():
                found.append((f"plugin:{key.split('@')[0]}", pathlib.Path(where)))
    return found


def skill_record(skill: pathlib.Path, label: str, overrides: dict, unreadable: list) -> dict:
    meta, other, body = frontmatter(read(skill, unreadable))
    name = meta.get("name") or skill.parent.name
    listing = (meta.get("description", "") + " " + meta.get("when_to_use", "")).strip()
    # skillOverrides applies to user and project skills; plugin skills are managed through /plugin.
    state = "on" if label.startswith("plugin:") else str(overrides.get(name, "on"))
    if meta.get("disable-model-invocation", "").lower() == "true" and state == "on":
        state = "user-invocable-only"
    listed = {"on": min(len(listing), LISTING_CAP), "name-only": len(name)}.get(state, 0)
    bundled = [p for p in skill.parent.rglob("*") if p.is_file() and p != skill]
    return {"name": name, "scope": label, "path": str(skill), "frontmatter": meta, "other_fields": other,
            "visibility": state, "model_invocable": state in ("on", "name-only"),
            "listing_chars": len(listing), "listing_truncated": state == "on" and len(listing) > LISTING_CAP,
            "always_est_tokens": est_tokens(listed),
            "body_lines": body.count("\n") + 1, "on_invoke_est_tokens": est_tokens(len(body)),
            "bundled_files": len(bundled)}


def agent_record(agent: pathlib.Path, label: str, unreadable: list) -> dict:
    meta, other, body = frontmatter(read(agent, unreadable))
    return {"name": meta.get("name") or agent.stem, "scope": label, "path": str(agent), "frontmatter": meta,
            "other_fields": other, "model": meta.get("model", "(inherits)"), "effort": meta.get("effort", "(unset)"),
            "tools": meta.get("tools", "(all)"), "listing_chars": len(meta.get("description", "")),
            "always_est_tokens": est_tokens(len(meta.get("description", ""))),
            "body_lines": body.count("\n") + 1, "on_spawn_est_tokens": est_tokens(len(body))}


def markdown_pieces(scope_list: list, overrides: dict, unreadable: list) -> dict:
    kinds = {"skills": [], "agents": [], "commands": [], "rules": [], "output_styles": []}
    for label, base in scope_list:
        for skill in sorted((base / "skills").glob("*/SKILL.md")):
            kinds["skills"].append(skill_record(skill, label, overrides, unreadable))
        for agent in sorted((base / "agents").rglob("*.md")):
            record = agent_record(agent, label, unreadable)
            if record["frontmatter"].get("name") or record["frontmatter"].get("description"):
                kinds["agents"].append(record)
        for kind, sub in (("commands", "commands"), ("rules", "rules"), ("output_styles", "output-styles")):
            for path in sorted((base / sub).rglob("*.md")):
                text = read(path, unreadable)
                meta, other, _ = frontmatter(text)
                item = {"name": meta.get("name") or path.stem, "scope": label, "path": str(path),
                        "chars": len(text), "est_tokens": est_tokens(len(text)), "frontmatter": meta, "other_fields": other}
                if kind == "rules":
                    item["loads"] = "when a matching file is read" if "paths" in meta else "session start"
                kinds[kind].append(item)
    return kinds


def missing_scripts(command: str, home: pathlib.Path, project: pathlib.Path) -> list:
    """Script files a hook command names that are not on disk. Paths it cannot resolve are left out, not guessed."""
    try:
        tokens = shlex.split(command.replace("\\", "/"))
    except ValueError:
        return []  # unbalanced quotes: unknown, not missing
    missing = []
    for token in tokens:
        if not re.search(r"\." + SCRIPT_EXT + r"$", token):
            continue
        if token.startswith("~/.claude/"):
            token = home.as_posix() + token[len("~/.claude"):]  # the audited --home, whatever it is named
        elif token.startswith("~/"):
            token = home.parent.as_posix() + token[1:]
        for var, target in (("CLAUDE_PROJECT_DIR", project), ("HOME", home.parent), ("USERPROFILE", home.parent)):
            for form in ("${" + var + "}", "$" + var, "%" + var + "%"):
                token = token.replace(form, target.as_posix())
        if "$" in token or "%" in token:
            continue  # an unresolved variable: unknown, not missing
        path = pathlib.Path(token)
        if not path.is_absolute():
            path = project / path
        if not path.exists():
            missing.append(token)
    return missing


def settings_view(home: pathlib.Path, project: pathlib.Path, settings: list, unreadable: list) -> dict:
    """Structure of the settings files: names, counts, hook definitions and the allowlisted values."""
    view = {"files": [], "hooks": [], "mcp_servers": []}
    for label, path, data in settings:
        values = {k: scalar(data[k]) for k in SAFE_SETTINGS if k in data}
        per_model = {}
        for model_id, conf in as_dict(data.get("modelSettings")).items():
            kept = {k: scalar(v) for k, v in as_dict(conf).items() if k in SAFE_SETTINGS}
            if kept:
                per_model[clean_name(model_id)] = kept
        if per_model:
            values["modelSettings"] = per_model
        perms = as_dict(data.get("permissions"))
        view["files"].append({
            "scope": label, "path": str(path), "keys": sorted(data), "values": values,
            "env_names": sorted(as_dict(data.get("env"))),
            "permissions": {k: (len(v) if isinstance(v, list) else scalar(v) if k == "defaultMode" else f"({type(v).__name__})")
                            for k, v in perms.items()},
            "permission_rules": {k: [r[:200] for r in v if isinstance(r, str)][:200]
                                 for k, v in perms.items() if k in ("allow", "ask", "deny") and isinstance(v, list)},
            "enabledPlugins": sorted(k for k, v in as_dict(data.get("enabledPlugins")).items() if v),
            "skillOverrides": {clean_name(k): (v if v in SKILL_STATES else "(other)")
                               for k, v in as_dict(data.get("skillOverrides")).items()}})
        for event, groups in as_dict(data.get("hooks")).items():
            for group in as_list(groups):
                group = as_dict(group)
                for hook in as_list(group.get("hooks")):
                    hook = as_dict(hook)
                    cmd = hook.get("command") if isinstance(hook.get("command"), str) else ""
                    known = {"command", "type", "timeout"} | SAFE_HOOK_OPTIONS
                    view["hooks"].append({
                        "scope": label, "event": str(event), "matcher": scalar(group.get("matcher", "")),
                        "type": scalar(hook.get("type", "command")), "command": cmd, "timeout": scalar(hook.get("timeout")),
                        "options": {k: scalar(hook[k]) for k in SAFE_HOOK_OPTIONS if k in hook},
                        "other_options": sorted(k for k in hook if k not in known),
                        "scripts_missing": missing_scripts(cmd, home, project)})
    user_config = read_json(home.parent / ".claude.json", unreadable)
    sources = [("project", as_dict(read_json(project / ".mcp.json", unreadable).get("mcpServers"))),
               ("user", as_dict(user_config.get("mcpServers")))]
    for key, conf in as_dict(user_config.get("projects")).items():
        try:
            same = pathlib.Path(key).resolve() == project
        except (OSError, ValueError):
            same = False
        if same:
            sources.append(("local", as_dict(as_dict(conf).get("mcpServers"))))
    for label, servers in sources:
        for name, conf in servers.items():
            view["mcp_servers"].append({"scope": label, "name": clean_name(name), "transport": scalar(as_dict(conf).get("type", "stdio"))})
    return view


def overlaps(pieces: dict, limit: int = 15) -> list:
    """Pairs of routing descriptions that share vocabulary. Candidates for a human or model to judge.

    Words that appear in more than a third of the descriptions say nothing about any one
    of them, so they are ignored. That adapts to the setup's own language and vocabulary
    without a stop-word list.
    """
    items = []
    for kind in ("skills", "agents"):
        for p in pieces[kind]:
            if kind == "skills" and p["visibility"] != "on":
                continue
            fm = p["frontmatter"]
            words = set(re.findall(r"[^\W\d_]{4,}", (fm.get("description", "") + " " + fm.get("when_to_use", "")).lower()))
            items.append((f"{kind[:-1]}:{p['name']}", words))
    seen_in = collections.Counter(w for _, words in items for w in words)
    common = {w for w, n in seen_in.items() if len(items) >= 6 and n > len(items) / 3}
    items = [(name, words - common) for name, words in items if len(words - common) >= 5]
    pairs = []
    for i, (a, wa) in enumerate(items):
        for b, wb in items[i + 1:]:
            score = len(wa & wb) / len(wa | wb)
            if score >= 0.2:
                pairs.append({"a": a, "b": b, "jaccard": round(score, 2), "shared": sorted(wa & wb)[:12]})
    return sorted(pairs, key=lambda x: -x["jaccard"])[:limit]


# ---------------------------------------------------------------- session history

def usage(home: pathlib.Path, days: int, unreadable: list) -> dict:
    if days <= 0 or not (home / "projects").is_dir():
        return {}
    cutoff_ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    cutoff_iso, cutoff_epoch = cutoff_ts.strftime("%Y-%m-%dT%H:%M:%S"), cutoff_ts.timestamp()
    tools, skills, agents, effort, slash = (collections.Counter() for _ in range(5))
    result_chars = collections.Counter()
    sessions = {"main": set(), "subagent": set()}
    messages: dict = {}   # message id -> (scope, model, usage); a resumed session repeats rows, so each id counts once
    rows_seen: set = set()  # row uuids, for the same reason
    tool_of: dict = {}
    order: dict = collections.defaultdict(list)  # main-session file -> [(timestamp, message id)] in the order first seen
    runs = collections.Counter()                 # subagent runs per agent type
    skipped = collections.Counter()
    root = home / "projects"
    files = [(p, "main") for p in root.glob("*/*.jsonl")] + [(p, "subagent") for p in root.glob("*/*/subagents/*.jsonl")]

    def agent_type_of(path: pathlib.Path) -> str:
        """Claude Code writes a small description beside each subagent transcript; it names the agent type."""
        for suffix in (".meta.json", ".json"):
            try:
                meta = json.loads(path.with_suffix(suffix).read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError):
                continue
            if isinstance(meta, dict) and isinstance(meta.get("agentType"), str):
                return clean_name(meta["agentType"])
        return "(unknown)"

    def take(row: dict, scope: str, fallback_session: str, agent: str) -> None:
        stamp = row.get("timestamp")
        if not isinstance(stamp, str) or not STAMP_RE.match(stamp):
            skipped["rows without a readable timestamp"] += 1
            return
        if stamp[:19] < cutoff_iso:
            return
        msg = row.get("message")
        if not isinstance(msg, dict):
            return
        uid = row.get("uuid")
        if isinstance(uid, str):
            if uid in rows_seen:
                return
            rows_seen.add(uid)
        session_id = row.get("sessionId") if isinstance(row.get("sessionId"), str) else fallback_session
        sessions[scope].add(session_id if scope == "main" else fallback_session)
        content = msg.get("content")
        blocks = [b for b in as_list(content) if isinstance(b, dict)]
        if row.get("type") == "assistant":
            mid = msg.get("id")
            # a "<synthetic>" message is written by Claude Code itself, not by a model: no request, no tokens
            if isinstance(mid, str) and isinstance(msg.get("usage"), dict) and msg.get("model") != "<synthetic>":
                model = clean_name(msg.get("model"))
                if mid not in messages:
                    if isinstance(row.get("effort"), str):
                        effort[f"{model} @ {clean_name(row['effort'])}"] += 1
                    if scope == "main":
                        order[fallback_session].append((stamp, mid))
                messages[mid] = (scope, model, msg["usage"], agent)
            for block in blocks:
                bid = block.get("id")
                if block.get("type") != "tool_use" or not isinstance(bid, str) or bid in tool_of:
                    continue
                name, args = clean_name(block.get("name")), as_dict(block.get("input"))
                tool_of[bid] = name
                tools[name] += 1
                if name == "Skill":
                    skills[clean_name(args.get("skill"))] += 1
                elif name in ("Agent", "Task"):
                    agents[clean_name(args["subagent_type"]) if args.get("subagent_type") else "(unspecified)"] += 1
        elif row.get("type") == "user":
            typed_text = content if isinstance(content, str) else " ".join(str(b.get("text", "")) for b in blocks)
            for typed_name in set(re.findall(r"<command-name>/?([\w:.-]{1,80})</command-name>", typed_text)):
                slash[typed_name] += 1
            for block in blocks:
                if block.get("type") != "tool_result":
                    continue
                body = block.get("content")
                if isinstance(body, str):
                    size = len(body)
                else:  # text blocks only: an image block is not text the model reads as characters
                    size = sum(len(b["text"]) for b in as_list(body) if isinstance(b, dict) and isinstance(b.get("text"), str))
                owner = block.get("tool_use_id")
                result_chars[tool_of.get(owner, "(call not in window)") if isinstance(owner, str) else "(call not in window)"] += size

    for path, scope in files:
        try:
            if path.stat().st_mtime < cutoff_epoch:
                continue
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable.append(f"{path}: {type(exc).__name__}")
            continue
        agent = agent_type_of(path) if scope == "subagent" else ""
        before = len(messages)
        with handle:
            for line in handle:
                if ('"tool_use"' not in line and '"tool_result"' not in line and '"usage"' not in line
                        and "<command-name>" not in line):
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        take(row, scope, str(path), agent)
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
                    skipped["session lines that could not be read"] += 1
        if scope == "subagent" and len(messages) > before:
            runs[agent] += 1
    for reason, count in skipped.items():
        unreadable.append(f"{root}: {count} {reason}, not counted")

    tokens = collections.defaultdict(collections.Counter)
    by_scope = collections.defaultdict(collections.Counter)
    by_agent = collections.defaultdict(collections.Counter)
    agent_models = collections.defaultdict(collections.Counter)
    for scope, model, use, agent in messages.values():
        if scope == "subagent":
            agent_models[agent][model] += 1
        for bucket in (tokens[f"{scope} | {model}"], by_scope[scope]) + ((by_agent[agent],) if scope == "subagent" else ()):
            bucket["input"] += num(use.get("input_tokens"))
            bucket["cache_write"] += num(use.get("cache_creation_input_tokens"))
            bucket["cache_read"] += num(use.get("cache_read_input_tokens"))
            bucket["output"] += num(use.get("output_tokens"))
            bucket["requests"] += 1
    total = collections.Counter()
    for bucket in by_scope.values():
        total.update(bucket)

    def prompt_side(b) -> int:
        return b["input"] + b["cache_write"] + b["cache_read"]

    def prompt_of(use: dict) -> int:
        return num(use.get("input_tokens")) + num(use.get("cache_creation_input_tokens")) + num(use.get("cache_read_input_tokens"))

    def seconds(stamp: str):
        try:
            return dt.datetime.fromisoformat(stamp[:19]).timestamp()
        except ValueError:
            return None

    # A cache rebuild: a request that wrote most of its prompt to the cache although the request before it,
    # in the same session, already held more than half of that prompt. The context was there and was paid for again.
    rebuilds = collections.defaultdict(lambda: {"count": 0, "tokens_rewritten": 0})
    lifetimes = collections.Counter()
    for sequence in order.values():
        prev = None
        for stamp, mid in sorted(sequence, key=lambda pair: pair[0]):
            _, model, use, _ = messages[mid]
            written, prompt = num(use.get("cache_creation_input_tokens")), prompt_of(use)
            split = as_dict(use.get("cache_creation"))
            long_lived = num(split.get("ephemeral_1h_input_tokens")) > 0
            if written:
                lifetimes["long" if long_lived else "short"] += written
            if prev and prompt and written > prompt / 2 and prev[2] > prompt / 2:
                now, then = seconds(stamp), seconds(prev[0])
                gap = now - then if now is not None and then is not None else 0
                if prompt < prev[2] / 2:
                    cause = "after the context was compacted or cleared"
                elif gap > (CACHE_LONG if long_lived else CACHE_SHORT):
                    cause = "after a pause longer than the cache lifetime"
                elif model != prev[1]:
                    cause = "after a model switch"
                else:
                    cause = "other (a change to tools or settings, or a cause the history does not show)"
                rebuilds[cause]["count"] += 1
                rebuilds[cause]["tokens_rewritten"] += written
            prev = (stamp, model, prompt)

    agent_runs = {}
    for agent, bucket in sorted(by_agent.items(), key=lambda kv: -kv[1]["output"]):
        n = max(runs[agent], 1)
        agent_runs[agent] = {
            "runs": runs[agent], "models": dict(agent_models[agent].most_common()),
            "requests_per_run": round(bucket["requests"] / n, 1),
            "output_tokens_per_run": round(bucket["output"] / n),
            "prompt_side_tokens_per_run": round(prompt_side(bucket) / n),
            "output_tokens": bucket["output"]}

    return {
        "window_days": days, "scope": "every project on this machine",
        "sessions": {k: len(v) for k, v in sessions.items()},
        "tokens_by_scope_and_model": {k: dict(v) for k, v in sorted(tokens.items())},
        "tokens_total": dict(total),
        "avg_prompt_tokens_per_request": {s: round(prompt_side(b) / b["requests"]) for s, b in sorted(by_scope.items()) if b["requests"]},
        "cache_read_share_of_prompt_tokens": round(total["cache_read"] / prompt_side(total), 4) if prompt_side(total) else None,
        "subagent_share_of_output_tokens": round(by_scope["subagent"]["output"] / total["output"], 4) if total["output"] else None,
        "tool_calls": dict(tools.most_common()), "skill_invocations": dict(skills.most_common()),
        "typed_commands": dict(slash.most_common()), "agent_spawns": dict(agents.most_common()),
        "agent_runs": agent_runs,
        "cache_rebuilds": {"definition": "a main-session request that wrote more than half of its prompt to the cache "
                                         "when the request before it in the same session was at least half that size; "
                                         "one cause is given per rebuild, checked in the order compaction, pause, model switch",
                           "by_cause": {k: dict(v) for k, v in sorted(rebuilds.items(), key=lambda kv: -kv[1]["tokens_rewritten"])}},
        "main_cache_write_tokens_by_lifetime": dict(lifetimes),
        "tool_result_chars": dict(result_chars.most_common(12)), "requests_by_model_and_effort": dict(effort.most_common())}


# ---------------------------------------------------------------- assembly

def build(home: pathlib.Path, project: pathlib.Path, days: int) -> dict:
    unreadable: list = []
    settings_raw = settings_files(home, project, unreadable)
    overrides: dict = {}
    for _, _, data in settings_raw:
        overrides.update(as_dict(data.get("skillOverrides")))
    instr = instruction_files(home, project, unreadable)
    pieces = markdown_pieces(scopes(home, project, settings_raw, unreadable), overrides, unreadable)
    settings = settings_view(home, project, settings_raw, unreadable)
    hist = usage(home, days, unreadable)
    active_style = next((f["values"]["outputStyle"] for f in reversed(settings["files"]) if f["values"].get("outputStyle")), None)
    style_tokens = sum(s["est_tokens"] for s in pieces["output_styles"] if active_style and s["name"].lower() == str(active_style).lower())
    fixed = {
        "instruction_files": sum(f["est_tokens"] for f in instr if f["loads"] == "session start"),
        "rules_without_paths": sum(r["est_tokens"] for r in pieces["rules"] if r.get("loads") == "session start"),
        "skill_listing": sum(s["always_est_tokens"] for s in pieces["skills"]),
        "agent_listing": sum(a["always_est_tokens"] for a in pieces["agents"]),
        "active_output_style": style_tokens}
    used_skills = {k.split(":")[-1] for k in {**hist.get("skill_invocations", {}), **hist.get("typed_commands", {})}}
    used_agents = {k.split(":")[-1] for k in hist.get("agent_spawns", {})}
    defined_agents = {a["name"] for a in pieces["agents"]}
    spawns = hist.get("agent_spawns", {})
    if hist:
        to_defined = sum(n for a, n in spawns.items() if a.split(":")[-1] in defined_agents)
        hist["share_of_spawns_to_agents_defined_here"] = round(to_defined / sum(spawns.values()), 4) if spawns else None
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"), "home": str(home), "project": str(project),
        "estimate_note": f"est_tokens = characters / {CHARS_PER_TOKEN}; an estimate, not a tokenizer count",
        "not_measured": [
            "the built-in system prompt and tool definitions", "MCP tool definitions (see /context in a session)",
            "bundled skills", "auto memory (MEMORY.md)", "sessions from other machines", "managed settings",
            "hooks defined by plugins or in skill and subagent frontmatter",
            "whether the skill listing exceeds its context budget",
            "hook script paths that depend on an unresolved variable"],
        "fixed_context_est_tokens": {**fixed, "total": sum(fixed.values())},
        "instruction_files": instr, **pieces, "settings": settings, "description_overlaps": overlaps(pieces),
        "usage": hist,
        "never_invoked_in_window": {
            "skills": sorted(s["name"] for s in pieces["skills"] if s["model_invocable"] and s["name"] not in used_skills),
            "agents": sorted(a["name"] for a in pieces["agents"] if a["name"] not in used_agents)} if hist else {},
        "spawned_without_definition_here": sorted(a for a in spawns if a.split(":")[-1] not in defined_agents),
        "unreadable": unreadable}


def summary(doc: dict) -> str:
    fx, use = doc["fixed_context_est_tokens"], doc["usage"]
    lines = [f"setup: {doc['home']}  project: {doc['project']}",
             f"fixed context every session (estimate, your files only): ~{fx['total']:,} tokens",
             "  " + "  ".join(f"{k}={v:,}" for k, v in fx.items() if k != "total"),
             f"pieces: {len(doc['instruction_files'])} instruction files, {len(doc['skills'])} skills, {len(doc['agents'])} agents, "
             f"{len(doc['commands'])} commands, {len(doc['rules'])} rules, {len(doc['settings']['hooks'])} hooks, "
             f"{len(doc['settings']['mcp_servers'])} MCP servers"]
    restricted = sum(1 for s in doc["skills"] if s["visibility"] != "on")
    if restricted:
        lines.append(f"skills restricted by settings or frontmatter (not fully listed to the model): {restricted}")
    long_files = [f for f in doc["instruction_files"] if f["lines"] > LONG_FILE_LINES]
    if long_files:
        lines.append(f"instruction files over {LONG_FILE_LINES} lines: "
                     + ", ".join(f"{pathlib.Path(f['path']).name} ({f['lines']})" for f in long_files))
    broken = [h for h in doc["settings"]["hooks"] if h["scripts_missing"]]
    if broken:
        lines.append(f"hooks naming a script that does not exist: {len(broken)}")
    if doc["description_overlaps"]:
        top = doc["description_overlaps"][0]
        lines.append(f"description overlaps to review: {len(doc['description_overlaps'])} (highest {top['a']} ~ {top['b']} at {top['jaccard']})")
    if use:
        t = use["tokens_total"]
        lines += [f"last {use['window_days']} days, every project on this machine: {use['sessions']['main']} sessions, "
                  f"{use['sessions']['subagent']} subagent runs, {t.get('requests', 0):,} requests",
                  f"  tokens: input={t.get('input', 0):,} cache_write={t.get('cache_write', 0):,} "
                  f"cache_read={t.get('cache_read', 0):,} output={t.get('output', 0):,}"]
        if use["avg_prompt_tokens_per_request"]:
            lines.append("  average prompt-side tokens per request: "
                         + ", ".join(f"{s} {n:,}" for s, n in use["avg_prompt_tokens_per_request"].items()))
        if use["cache_read_share_of_prompt_tokens"] is not None and use["subagent_share_of_output_tokens"] is not None:
            lines.append(f"  cache reads are {use['cache_read_share_of_prompt_tokens']:.1%} of prompt-side tokens; "
                         f"subagents produced {use['subagent_share_of_output_tokens']:.1%} of output tokens")
        rewritten = sum(v["tokens_rewritten"] for v in use["cache_rebuilds"]["by_cause"].values())
        if rewritten:
            top_cause, top = next(iter(use["cache_rebuilds"]["by_cause"].items()))
            lines.append(f"  cache rebuilds: {sum(v['count'] for v in use['cache_rebuilds']['by_cause'].values()):,} "
                         f"rewrote {rewritten:,} tokens; most {top_cause} ({top['tokens_rewritten']:,})")
        never = doc["never_invoked_in_window"]
        lines.append(f"  never invoked in the window: {len(never['skills'])} of "
                     f"{sum(1 for s in doc['skills'] if s['model_invocable'])} model-invocable skills, "
                     f"{len(never['agents'])} of {len(doc['agents'])} agents")
    if doc["unreadable"]:
        lines.append(f"unreadable or unparsed: {len(doc['unreadable'])} (listed in the JSON)")
    return "\n".join(lines)


def compare(before: dict, after: dict) -> str:
    """What changed between two measurements of the same setup."""
    def pick(doc: dict) -> dict:
        use = doc.get("usage") or {}
        total = use.get("tokens_total", {})
        rows = {f"fixed context: {k} (est. tokens)": v for k, v in doc["fixed_context_est_tokens"].items()}
        rows.update({"skills": len(doc["skills"]), "agents": len(doc["agents"]), "hooks": len(doc["settings"]["hooks"]),
                     "description overlaps to review": len(doc["description_overlaps"])})
        if use:
            rows.update({
                "skills never invoked in window": len(doc["never_invoked_in_window"]["skills"]),
                "agents never invoked in window": len(doc["never_invoked_in_window"]["agents"]),
                "output tokens per session": round(total.get("output", 0) / max(use["sessions"]["main"], 1)),
                "cache-read share of prompt tokens": use.get("cache_read_share_of_prompt_tokens"),
                "share of spawns to agents defined here": use.get("share_of_spawns_to_agents_defined_here")})
            for scope, value in (use.get("avg_prompt_tokens_per_request") or {}).items():
                rows[f"average prompt-side tokens per request ({scope})"] = value
        return rows

    a, b = pick(before), pick(after)
    lines = [f"before: {before['generated']}   after: {after['generated']}"]
    for key in sorted(set(a) | set(b)):
        old, new = a.get(key), b.get(key)
        if old is None or new is None:
            lines.append(f"  {key}: {old} -> {new} (not measured on one side)")
        elif old != new:
            pct = f" ({(new - old) / old:+.1%})" if old else ""
            lines.append(f"  {key}: {old:,} -> {new:,}{pct}")
    if len(lines) == 1:
        lines.append("  no measured difference")
    lines.append("usage figures describe each measurement's own window; compare them only when the windows do not overlap")
    return "\n".join(lines)


def piece(path: pathlib.Path) -> dict:
    """One skill or subagent file measured on its own, whether or not it is installed anywhere."""
    unreadable: list = []
    if path.is_dir():
        path = path / "SKILL.md"
    record = skill_record(path, "standalone", {}, unreadable) if path.name == "SKILL.md" else agent_record(path, "standalone", unreadable)
    if path.name == "SKILL.md":
        # text the skill can send its reader to, totalled per folder; none of it loads until it is read
        folders = collections.defaultdict(lambda: {"files": 0, "est_tokens": 0})
        for p in path.parent.rglob("*"):
            if p.is_file() and p.parent != path.parent and ".git" not in p.parts and p.suffix in (".md", ".txt"):
                entry = folders[p.relative_to(path.parent).parts[0]]
                entry["files"] += 1
                entry["est_tokens"] += est_tokens(p.stat().st_size)
        record["bundled"] = dict(sorted(folders.items()))
    record["unreadable"] = unreadable
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_home = os.environ.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude")
    ap.add_argument("--home", default=default_home, help="user-level directory (default: $CLAUDE_CONFIG_DIR, else ~/.claude)")
    ap.add_argument("--project", default=".", help="project directory (default: current directory)")
    ap.add_argument("--days", type=int, default=30, help="days of session history to read; 0 skips it (default: 30)")
    ap.add_argument("--out", default="", help="write the full JSON here")
    ap.add_argument("--compare", default="", help="an earlier JSON written with --out; prints what changed since")
    ap.add_argument("--piece", default="", help="measure one skill folder, SKILL.md or subagent file on its own, and stop")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.piece:
        target = pathlib.Path(args.piece).expanduser()
        if not target.exists():
            print(f"no file or folder at {target}", file=sys.stderr)
            return 2
        print(json.dumps(piece(target), indent=2, ensure_ascii=False))
        return 0
    home, project = pathlib.Path(args.home).expanduser(), pathlib.Path(args.project).expanduser().resolve()
    if not home.is_dir():
        print(f"no Claude Code directory at {home}", file=sys.stderr)
        return 2
    doc = build(home, project, args.days)
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(summary(doc))
    if args.compare:
        print("\n" + compare(json.loads(pathlib.Path(args.compare).read_text(encoding="utf-8")), doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
