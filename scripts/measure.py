#!/usr/bin/env python3
"""Measure a Claude Code setup: what exists, when each piece loads, what it costs, how it is used.

This is the deterministic half of the audit. It counts and lists; it does not judge.
Everything it reports is either read from disk or computed from local session
history, and each estimate is labelled as one.

In:  --home     the user-level Claude Code directory (default ~/.claude)
     --project  a project directory (default: current directory)
     --days     how far back to read session history (default 30; 0 skips it)
     --out      where to write the full JSON (default: stdout summary only)
     --compare  an earlier JSON written with --out; also prints what changed since
Out: a JSON document (see `build()`), and a short text summary on stdout.
Fails: exit 2 if --home does not exist. A file that cannot be read or parsed is
       listed under `unreadable` and its content is left out of the figures.

Scope: pieces are those of the user level, the given project and enabled plugins.
Usage covers every project on this machine, because user-level pieces serve all
of them; an agent defined in another project shows up in usage without a
definition here, and is listed under `spawned_without_definition_here`.

Privacy: reads local files only and makes no network call. From settings it keeps
key names, hook definitions, counts and a fixed list of non-secret values, never
`env` values or MCP server arguments. From frontmatter it keeps a fixed list of
fields and only the names of any others. From session history it keeps counts and
token totals, never text.

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
import sys

CHARS_PER_TOKEN = 4  # rough, for English prose; every figure derived from it is an estimate
LISTING_CAP = 1536   # description + when_to_use are truncated to this in the skill listing
IMPORT_DEPTH = 4     # CLAUDE.md imports are followed to this many hops
# Frontmatter fields whose values are configuration, safe to copy. Anything else
# (an inline `mcpServers` or `hooks` block can hold credentials) is recorded by name only.
SAFE_FIELDS = {"name", "description", "when_to_use", "model", "effort", "tools", "disallowedTools", "allowed-tools",
               "disable-model-invocation", "user-invocable", "context", "agent", "paths", "permissionMode", "maxTurns",
               "skills", "memory", "background", "isolation", "color", "argument-hint", "version", "license"}
# Settings whose values the review needs and that cannot hold a secret.
SAFE_SETTINGS = ("model", "outputStyle", "effortLevel", "autoCompactWindow", "modelSettings", "cleanupPeriodDays",
                 "disableBundledSkills", "alwaysThinkingEnabled", "autoMemoryEnabled", "includeCoAuthoredBy")
GENERIC_AGENTS = {"general-purpose", "general", "claude", "fork", "(unspecified)"}
BUILT_IN_AGENTS = {"Explore", "Plan", "claude-code-guide", "statusline-setup"}
STOP = set("this that with from when what which will your have into only also used uses using than then them they "
           "their there here such each must should would could about after before where while other more most "
           "does done make made need needs want wants user users claude skill skills agent agents para como "
           "quando isso essa esse este esta mais pelo pela uma umas seus suas".split())


def est_tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def read(path: pathlib.Path, unreadable: list) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        unreadable.append(f"{path}: {exc}")
        return ""


def read_json(path: pathlib.Path, unreadable: list) -> dict:
    """A JSON object from disk, or {} with the reason recorded. A missing file is not an error."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        unreadable.append(f"{path}: {exc}")
        return {}
    if not isinstance(data, dict):
        unreadable.append(f"{path}: expected a JSON object, found {type(data).__name__}")
        return {}
    return data


def frontmatter(text: str):
    """Reads top-level `key: value` pairs. Returns (safe fields, names of other fields, body).

    Indented lines belong to the key above them. For a safe field they are joined
    into its value (a YAML list becomes "a, b"); for any other field they are dropped.
    """
    if not text.startswith("---"):
        return {}, [], text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, [], text
    data, other, key = {}, [], None
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key in SAFE_FIELDS:
                data[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
            else:
                other.append(key)
        elif key in SAFE_FIELDS and line.strip():
            item = line.strip()
            if item.startswith("- "):
                item = item[2:].strip().strip("\"'")
                data[key] = f"{data[key]}, {item}" if data[key] else item
            else:
                data[key] = (data[key] + " " + item).strip()
    return data, other, text[end + 4:]


# ---------------------------------------------------------------- pieces on disk

def instruction_files(home: pathlib.Path, project: pathlib.Path, unreadable: list) -> list:
    """Instruction files that load at session start, with the files they import.

    AGENTS.md is listed separately as `loads: "only if no CLAUDE.md is found"`, since
    by default Claude Code reads it only in that case.
    """
    roots = [(home / "CLAUDE.md", "user")]
    for d in reversed([project, *project.parents]):
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md"):
            p = d / name
            if p != home / "CLAUDE.md":
                roots.append((p, "project" if d == project else "ancestor"))
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
        fallback = path.name == "AGENTS.md" and has_claude_md
        out.append({"path": str(path), "scope": scope, "imported_by": via, "chars": len(text),
                    "lines": text.count("\n") + 1, "est_tokens": est_tokens(len(text)),
                    "loads": "only if no CLAUDE.md is found" if fallback else "session start"})
        if depth >= IMPORT_DEPTH or fallback:
            return
        body = re.sub(r"```.*?```", "", text, flags=re.S)
        for ref in re.findall(r"(?<![\w`@])@((?:~|\.{1,2})?[\w./\\-]+\.(?:md|txt|ya?ml|json))", body):
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
            path = pathlib.Path(str(as_dict(entry).get("installPath", "")))
            if as_dict(entry).get("installPath") and path.is_dir():
                found.append((f"plugin:{key.split('@')[0]}", path))
    return found


def markdown_pieces(scope_list: list, overrides: dict, unreadable: list) -> dict:
    kinds = {"skills": [], "agents": [], "commands": [], "rules": [], "output_styles": []}
    for label, base in scope_list:
        for skill in sorted((base / "skills").glob("*/SKILL.md")):
            meta, other, body = frontmatter(read(skill, unreadable))
            name = meta.get("name") or skill.parent.name
            listing = (meta.get("description", "") + " " + meta.get("when_to_use", "")).strip()
            # skillOverrides applies to user and project skills; plugin skills are managed through /plugin.
            state = "on" if label.startswith("plugin:") else str(overrides.get(name, "on"))
            if meta.get("disable-model-invocation", "").lower() == "true" and state == "on":
                state = "user-invocable-only"
            listed = {"on": min(len(listing), LISTING_CAP), "name-only": len(name)}.get(state, 0)
            refs = [p for p in skill.parent.rglob("*") if p.is_file() and p != skill]
            kinds["skills"].append({
                "name": name, "scope": label, "path": str(skill), "frontmatter": meta, "other_fields": other,
                "visibility": state, "model_invocable": state in ("on", "name-only"),
                "listing_chars": len(listing), "listing_truncated": state == "on" and len(listing) > LISTING_CAP,
                "always_est_tokens": est_tokens(listed),
                "body_lines": body.count("\n") + 1, "on_invoke_est_tokens": est_tokens(len(body)),
                "bundled_files": len(refs)})
        for agent in sorted((base / "agents").rglob("*.md")):
            meta, other, body = frontmatter(read(agent, unreadable))
            if not meta.get("name") and not meta.get("description"):
                continue
            kinds["agents"].append({
                "name": meta.get("name") or agent.stem, "scope": label, "path": str(agent), "frontmatter": meta,
                "other_fields": other, "model": meta.get("model", "(inherits)"), "effort": meta.get("effort", "(unset)"),
                "tools": meta.get("tools", "(all)"), "listing_chars": len(meta.get("description", "")),
                "always_est_tokens": est_tokens(len(meta.get("description", ""))),
                "body_lines": body.count("\n") + 1, "on_spawn_est_tokens": est_tokens(len(body))})
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


def settings_view(home: pathlib.Path, project: pathlib.Path, settings: list, unreadable: list) -> dict:
    """Structure of the settings files: names, counts, hook definitions and the non-secret values."""
    view = {"files": [], "hooks": [], "mcp_servers": []}
    for label, path, data in settings:
        perms = as_dict(data.get("permissions"))
        view["files"].append({
            "scope": label, "path": str(path), "keys": sorted(data),
            "values": {k: data[k] for k in SAFE_SETTINGS if k in data},
            "env_names": sorted(as_dict(data.get("env"))),
            "permissions": {k: (len(v) if isinstance(v, list) else v) for k, v in perms.items()},
            "enabledPlugins": sorted(k for k, v in as_dict(data.get("enabledPlugins")).items() if v),
            "skillOverrides": as_dict(data.get("skillOverrides"))})
        for event, groups in as_dict(data.get("hooks")).items():
            for group in as_list(groups):
                group = as_dict(group)
                for hook in as_list(group.get("hooks")):
                    hook = as_dict(hook)
                    cmd = str(hook.get("command", ""))
                    scripts = re.findall(r"[\"']?((?:~|\$HOME|\$CLAUDE_PROJECT_DIR|[A-Za-z]:|/|\.)[^\s\"']*\.(?:py|sh|js|mjs|ts|ps1|cmd|bat))", cmd)
                    missing = []
                    for s in scripts:
                        resolved = s.replace("$HOME", str(pathlib.Path.home())).replace("$CLAUDE_PROJECT_DIR", str(project))
                        if not pathlib.Path(os.path.expanduser(resolved)).exists():
                            missing.append(s)
                    options = {k: v for k, v in hook.items() if k not in ("command", "type", "timeout", "prompt", "headers", "url")
                               and isinstance(v, (str, int, float, bool))}
                    view["hooks"].append({"scope": label, "event": event, "matcher": str(group.get("matcher", "")),
                                          "type": hook.get("type", "command"), "command": cmd,
                                          "timeout": hook.get("timeout"), "options": options, "scripts_missing": missing})
    for label, path in (("project", project / ".mcp.json"), ("user", home.parent / ".claude.json")):
        for name, conf in as_dict(read_json(path, unreadable).get("mcpServers")).items():
            view["mcp_servers"].append({"scope": label, "name": name, "transport": as_dict(conf).get("type", "stdio")})
    return view


def overlaps(pieces: dict, limit: int = 15) -> list:
    """Pairs of routing descriptions that share vocabulary. Candidates for a human or model to judge."""
    items = []
    for kind in ("skills", "agents"):
        for p in pieces[kind]:
            if kind == "skills" and p["visibility"] != "on":
                continue
            fm = p["frontmatter"]
            words = set(re.findall(r"[a-zà-ú]{4,}", (fm.get("description", "") + " " + fm.get("when_to_use", "")).lower())) - STOP
            if len(words) >= 5:
                items.append((f"{kind[:-1]}:{p['name']}", words))
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
    sessions = {"main": 0, "subagent": 0}
    messages: dict = {}   # message id -> (scope, model, usage); a resumed session repeats ids, so last one wins
    tool_seen: set = set()
    bad_lines = 0
    root = home / "projects"
    files = [(p, "main") for p in root.glob("*/*.jsonl")] + [(p, "subagent") for p in root.glob("*/*/subagents/*.jsonl")]
    for path, scope in files:
        try:
            if path.stat().st_mtime < cutoff_epoch:
                continue
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable.append(f"{path}: {exc}")
            continue
        tool_of, active = {}, False
        with handle:
            for line in handle:
                if ('"tool_use"' not in line and '"tool_result"' not in line and '"usage"' not in line
                        and "<command-name>" not in line):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    bad_lines += 1
                    continue
                if not isinstance(row, dict) or str(row.get("timestamp", "9"))[:19] < cutoff_iso:
                    continue
                msg = row.get("message")
                if not isinstance(msg, dict):
                    continue
                active = True
                content = msg.get("content")
                blocks = [b for b in as_list(content) if isinstance(b, dict)]
                if row.get("type") == "assistant":
                    if msg.get("id") and isinstance(msg.get("usage"), dict):
                        if msg["id"] not in messages and row.get("effort"):
                            effort[f"{msg.get('model', '?')} @ {row['effort']}"] += 1
                        messages[msg["id"]] = (scope, str(msg.get("model", "?")), msg["usage"])
                    for block in blocks:
                        if block.get("type") != "tool_use" or block.get("id") in tool_seen:
                            continue
                        tool_seen.add(block.get("id"))
                        name, args = str(block.get("name", "?")), as_dict(block.get("input"))
                        tool_of[block.get("id")] = name
                        tools[name] += 1
                        if name == "Skill":
                            skills[str(args.get("skill", "?"))] += 1
                        elif name in ("Agent", "Task"):
                            agents[str(args.get("subagent_type") or "(unspecified)")] += 1
                elif row.get("type") == "user":
                    typed_text = content if isinstance(content, str) else " ".join(str(b.get("text", "")) for b in blocks)
                    for typed_name in set(re.findall(r"<command-name>/?([\w:.-]+)</command-name>", typed_text)):
                        slash[typed_name] += 1
                    for block in blocks:
                        if block.get("type") == "tool_result":
                            body = block.get("content")
                            if isinstance(body, str):
                                size = len(body)
                            else:  # text blocks only: an image block is not text the model reads as characters
                                size = sum(len(str(b.get("text", ""))) for b in as_list(body) if isinstance(b, dict))
                            result_chars[tool_of.get(block.get("tool_use_id"), "?")] += size
        if active:
            sessions[scope] += 1
    if bad_lines:
        unreadable.append(f"{root}: {bad_lines} session lines were not valid JSON and were not counted")

    tokens = collections.defaultdict(collections.Counter)
    by_scope = collections.defaultdict(collections.Counter)
    for scope, model, use in messages.values():
        for bucket in (tokens[f"{scope} | {model}"], by_scope[scope]):
            bucket["input"] += use.get("input_tokens") or 0
            bucket["cache_write"] += use.get("cache_creation_input_tokens") or 0
            bucket["cache_read"] += use.get("cache_read_input_tokens") or 0
            bucket["output"] += use.get("output_tokens") or 0
            bucket["requests"] += 1
    total = collections.Counter()
    for bucket in by_scope.values():
        total.update(bucket)

    def prompt_side(b) -> int:
        return b["input"] + b["cache_write"] + b["cache_read"]

    typed = sum(n for a, n in agents.items() if a not in GENERIC_AGENTS)
    return {
        "window_days": days, "scope": "every project on this machine", "sessions": sessions,
        "tokens_by_scope_and_model": {k: dict(v) for k, v in sorted(tokens.items())},
        "tokens_total": dict(total),
        "avg_prompt_tokens_per_request": {s: round(prompt_side(b) / b["requests"]) for s, b in sorted(by_scope.items()) if b["requests"]},
        "cache_read_share_of_prompt_tokens": round(total["cache_read"] / prompt_side(total), 4) if prompt_side(total) else None,
        "subagent_share_of_output_tokens": round(by_scope["subagent"]["output"] / total["output"], 4) if total["output"] else None,
        "tool_calls": dict(tools.most_common()), "skill_invocations": dict(skills.most_common()),
        "typed_commands": dict(slash.most_common()), "agent_spawns": dict(agents.most_common()),
        "typed_agent_share_of_spawns": round(typed / sum(agents.values()), 4) if agents else None,
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
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"), "home": str(home), "project": str(project),
        "estimate_note": f"est_tokens = characters / {CHARS_PER_TOKEN}; an estimate, not a tokenizer count",
        "not_measured": ["the built-in system prompt and tool definitions", "MCP tool definitions (see /context in a session)",
                         "bundled skills", "auto memory (MEMORY.md)", "sessions from other machines",
                         "whether the skill listing exceeds its context budget", "which agent each request's effort belongs to"],
        "fixed_context_est_tokens": {**fixed, "total": sum(fixed.values())},
        "instruction_files": instr, **pieces, "settings": settings, "description_overlaps": overlaps(pieces),
        "usage": hist,
        "never_invoked_in_window": {
            "skills": sorted(s["name"] for s in pieces["skills"] if s["model_invocable"] and s["name"] not in used_skills),
            "agents": sorted(a["name"] for a in pieces["agents"] if a["name"] not in used_agents)} if hist else {},
        "spawned_without_definition_here": sorted(
            a for a in hist.get("agent_spawns", {}) if a.split(":")[-1] not in defined_agents and a not in GENERIC_AGENTS
            and a not in BUILT_IN_AGENTS) if hist else [],
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
    long_files = [f for f in doc["instruction_files"] if f["lines"] > 200]
    if long_files:
        lines.append("instruction files over 200 lines: " + ", ".join(f"{pathlib.Path(f['path']).name} ({f['lines']})" for f in long_files))
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
                "typed-agent share of spawns": use.get("typed_agent_share_of_spawns")})
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", default=str(pathlib.Path.home() / ".claude"), help="user-level directory (default: ~/.claude)")
    ap.add_argument("--project", default=".", help="project directory (default: current directory)")
    ap.add_argument("--days", type=int, default=30, help="days of session history to read; 0 skips it (default: 30)")
    ap.add_argument("--out", default="", help="write the full JSON here")
    ap.add_argument("--compare", default="", help="an earlier JSON written with --out; prints what changed since")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
