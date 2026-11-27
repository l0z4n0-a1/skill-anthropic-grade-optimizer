#!/usr/bin/env python3
"""Measure a Claude Code setup: what exists, when each piece loads, what it costs, how it is used.

This is the deterministic half of the review. It counts and lists; it does not judge.
Everything it reports is read from disk or computed from local session history,
and each estimate is labelled as one.

Flags (all optional; --help prints the same list):
  --home DIR            user-level Claude Code directory (default: $CLAUDE_CONFIG_DIR, else ~/.claude)
  --project DIR         project directory (default: the current directory)
  --days N              days of session history to read; 0 skips it (default: 30, at most 36500)
  --out FILE            also write the full JSON here (created readable by the current user only
                        where the system allows it); the directory must exist
  --compare FILE        a setup JSON written earlier with --out; also prints what changed since
  --piece PATH          measure one skill folder, one SKILL.md or one subagent .md file on its own
  --user-config FILE    the user-level .claude.json (default: see "Where .claude.json is looked for")
  --no-external-reads   read nothing outside --home and --project (for reviewing someone else's setup)

Modes and combinations:
  setup (default)       --home --project --days --out --compare --user-config --no-external-reads
  --piece PATH          only --out and --no-external-reads; --home, --project, --days, --user-config
                        and --compare describe a setup and are refused with --piece
  --out and --compare   must name different files: --out would replace the baseline before it is read
  --compare             the baseline must be a complete setup JSON of this schema_version, from the same --home,
                        --project, read scope (--no-external-reads or not) and .claude.json; it is checked
                        in full before --out is written, and any mismatch is exit 2 with --out untouched;
                        a different --days window leaves the usage rows out and says so

Exit codes:
  0  measured; problems with single files are listed under `unreadable`, not fatal
  1  the measurement was made but --out could not be written (I/O error); the summary still printed
  2  the command line or an input cannot be used: bad flag or combination, --home, --project or
     --piece that does not exist or is not what the mode needs, a --compare baseline that is not
     valid, --out equal to --compare. A message on stderr says what to change; these cases do not
     end in a traceback.

Output. --out writes one JSON object; stdout gets a short text summary (setup) or the same JSON (--piece).
Both carry "schema_version": 1 (an integer, raised only when a key is removed or changes meaning) and
"kind": "setup" or "piece". New keys can appear without a version bump: ignore keys you do not know.
Units: `*_chars` and `chars` count characters of the decoded text (not bytes); `est_tokens` is
characters / 4, an estimate; the figures under `usage` are token counts Claude Code logged;
shares are fractions between 0 and 1 rounded to 4 places, or null when there is nothing to divide;
`generated` is UTC. Paths are written as the system prints them.
  setup, top-level keys: schema_version, kind, generated, home, project, user_config {path, basis, found},
    read_scope {confine_external_reads, skipped_outside_scope}, policy, estimate_note, not_measured,
    skill_listing_cap {chars, source}, instruction_mode {value, source, note}, fixed_context_est_tokens,
    instruction_files, skills, agents, commands, rules, output_styles, plugins, settings,
    description_overlaps, usage, never_invoked_in_window, spawned_without_definition_here, unreadable.
    Optional: `usage` is {} when --days is 0 or <home>/projects does not exist, and then
    `never_invoked_in_window` is {} too. Records of pieces carry `parse_notes` (what the line-based
    frontmatter reader did not interpret) and, for skills, `description_source`.
  piece, top-level keys: schema_version, kind, piece_type ("skill" or "agent"), the record of the piece
    (the same fields as an entry of `skills` or `agents`), bundled (skills only: est_tokens of the .md and
    .txt files in its subfolders, by folder), estimate_note, policy, read_scope, not_measured, unreadable.
`policy` lists the named constants at the top of this file that decide how the report is cut (top-N,
the Jaccard cutoff for overlaps, text limits, the history window). They are presentation choices, not
facts about Claude Code; those are in kb/harness.json.

Scope of the measurement. Pieces are those of the user level, the given project and the enabled
plugins whose install entry applies to this project. An enabled plugin is one whose entry in the
effective settings (user, then project, then local; a later `false` undoes an earlier `true`) is true;
an install entry of scope project or local counts only for the project named in its projectPath.
A plugin skill is a folder under skills/ or, when the plugin has no skills/ folder and its manifest has
no `skills` key, a SKILL.md at the plugin root. Usage covers the recognized transcripts under
<home>/projects (every project folder there), because user-level pieces serve all of them; an
agent with no definition here (built in, or defined elsewhere) is listed under
`spawned_without_definition_here`. Names in the history are matched to pieces by their qualified name
(`plugin:skill`); a bare name that fits several pieces credits all of them and is listed in
`usage.attribution_ambiguous`. What the script does not read or apply is listed under `not_measured`.

Where .claude.json is looked for: Claude Code keeps it inside the config directory when
CLAUDE_CONFIG_DIR is set and at ~/.claude.json otherwise (kb/snapshots/cc-claude-directory.md). Here:
--user-config wins; else inside --home when --home is the CLAUDE_CONFIG_DIR of this shell; else
beside --home when --home is named `.claude`; else inside --home. The last two are assumptions about
someone else's layout, and `user_config.basis` in the output says which rule was used.

What it reads (nothing is written except --out, and no network call is made):
  - <home>: CLAUDE.md, settings.json, skills/, agents/, commands/, rules/, output-styles/,
    plugins/installed_plugins.json and the transcripts under projects/ (all project folders)
  - the user-level .claude.json (server names and transports only)
  - the project: CLAUDE.md, CLAUDE.local.md, .claude/CLAUDE.md, AGENTS.md and .claude/AGENTS.md in the
    project directory and in EVERY directory above it up to the filesystem root, .claude/ and .mcp.json
  - files named by `@path` imports in instruction files, to the documented depth of four hops, wherever
    they are (including outside --home and the project; `~` means the audited user's home when it is
    known, else the import is left unresolved); symlinks are followed to their targets
  - the install folder of each enabled plugin, wherever installed_plugins.json points
  - hook script paths: whether they exist is checked, their contents are not read
--no-external-reads drops every read whose resolved path is outside --home and --project (ancestor
directories, imports and symlink targets elsewhere, plugin folders elsewhere, a .claude.json beside
--home unless --user-config names it, the sidecar file beside each subagent transcript, a --piece that
is a link leaving its own folder) and lists what it declined under `read_scope` and `not_measured`.

Privacy: it copies what a review needs and nothing else: the values of a fixed list of frontmatter
fields and settings, hook definitions (event, matcher, command, timeout and a fixed list of options),
permission rules, and the names of servers, plugins, models, tools, skills and agents. It never copies
`env` values, MCP server arguments, message text, or the contents of any frontmatter block outside the
list. What it copies, it copies as written: a secret typed into a description, a hook command or a
permission rule appears in the output, so treat the JSON like the files it was read from, and know
that opening it in a Claude session shows that session every field it kept. With --out the file is
created with mode 0600 where the system has modes (an existing file is restricted to 0600 before it is
emptied and rewritten, so the new content is never in a file others can read). On Windows that mode has no effect: the file
gets the access rules of its folder (the ACL it inherits), so write it somewhere only you can read.

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

SCHEMA_VERSION = 1
HAS_MODES = hasattr(os, "fchmod")  # POSIX file modes; on Windows the folder's ACL decides who can read the report
CHARS_PER_TOKEN = 4  # an estimating convention, not a fact about Claude Code; every figure from it is labelled an estimate
# Facts about Claude Code live in kb/harness.json, each tied to the claim that documents it.
_HARNESS = json.loads((pathlib.Path(__file__).resolve().parent.parent / "kb" / "harness.json").read_text(encoding="utf-8"))
LISTING_CAP = _HARNESS["skill_listing_cap_chars"]["value"]
IMPORT_DEPTH = _HARNESS["instruction_import_max_hops"]["value"]
LONG_FILE_LINES = _HARNESS["instruction_file_recommended_max_lines"]["value"]
CACHE_SHORT = _HARNESS["cache_lifetime_seconds_short"]["value"]
CACHE_LONG = _HARNESS["cache_lifetime_seconds_long"]["value"]

# Report policy: how this report is cut. Choices of presentation, not facts about Claude Code; echoed under `policy`.
DEFAULT_DAYS = 30             # session-history window when --days is not given
MAX_DAYS = 36500              # largest --days accepted (a century; keeps the date arithmetic in range)
TOP_OVERLAPS = 15             # description pairs listed, most similar first
OVERLAP_MIN_JACCARD = 0.2     # a pair is listed from this word-set overlap (Jaccard) upward
OVERLAP_MIN_WORDS = 5         # a description needs this many distinctive words to be compared at all
OVERLAP_MIN_WORD_CHARS = 4    # shorter words are not counted
OVERLAP_COMMON_SHARE = 1 / 3  # a word in more than this share of descriptions says nothing about any one of them
OVERLAP_COMMON_MIN_PIECES = 6  # the common-word filter applies from this many compared descriptions
OVERLAP_SHARED_SHOWN = 12     # shared words listed per pair
TOP_TOOL_RESULTS = 12         # tools listed in usage.tool_result_chars
MAX_VALUE = 2000              # longest frontmatter value kept, in characters
MAX_SCALAR = 200              # longest settings or hook scalar kept, in characters
MAX_RULE = 200                # longest permission rule kept, in characters
MAX_RULES = 200               # permission rules kept per list
NAME_MAX = 80                 # longest model, tool, skill or agent name kept from history
REBUILD_SHARE = 0.5           # a cache rebuild writes more than this share of its prompt, after a request holding more than this share of it
COMPACTION_SHRINK = 0.5       # a prompt under this share of the previous one is read as the context having been compacted
TAIL_BYTES = 65536            # end of a transcript read to tell whether the whole file lies before the window
SKIPPED_SHOWN = 50            # reads declined under --no-external-reads that are listed by path

POLICY = {
    "default_days": DEFAULT_DAYS, "chars_per_token": CHARS_PER_TOKEN, "overlap_top": TOP_OVERLAPS,
    "overlap_min_jaccard": OVERLAP_MIN_JACCARD, "overlap_min_words": OVERLAP_MIN_WORDS,
    "overlap_min_word_chars": OVERLAP_MIN_WORD_CHARS, "overlap_common_share": round(OVERLAP_COMMON_SHARE, 4),
    "overlap_common_min_pieces": OVERLAP_COMMON_MIN_PIECES, "overlap_shared_shown": OVERLAP_SHARED_SHOWN,
    "top_tool_results": TOP_TOOL_RESULTS, "max_value_chars": MAX_VALUE, "max_scalar_chars": MAX_SCALAR,
    "max_rule_chars": MAX_RULE, "max_rules_per_list": MAX_RULES, "name_max_chars": NAME_MAX,
    "rebuild_share": REBUILD_SHARE, "compaction_shrink": COMPACTION_SHRINK, "tail_bytes": TAIL_BYTES}

# Allowlists. A value is copied only when its key is named here; any other key is recorded by name.
SAFE_FIELDS = {"name", "description", "when_to_use", "model", "effort", "tools", "disallowedTools", "allowed-tools",
               "disable-model-invocation", "user-invocable", "context", "agent", "paths", "permissionMode", "maxTurns",
               "skills", "memory", "background", "isolation", "color", "argument-hint", "version", "license"}
SAFE_SETTINGS = {"model", "outputStyle", "effortLevel", "autoCompactWindow", "cleanupPeriodDays",
                 "disableBundledSkills", "alwaysThinkingEnabled", "autoMemoryEnabled", "skillListingMaxDescChars"}
SAFE_HOOK_OPTIONS = {"onFailure", "async", "once", "continueOnBlock"}
TEXT_FIELDS = {"description", "when_to_use", "argument-hint"}  # prose; every other safe field is a scalar or a list
SKILL_STATES = {"on", "name-only", "user-invocable-only", "off"}
INSTRUCTION_MODES = ("claude-md-or-agents-md", "claude-md-and-agents-md", "claude-md", "managed-only")
INSTRUCTION_PLUGIN_ID = "cc-plugin-agents-md@builtin"
MANIFEST_PATH_KEYS = ("skills", "commands", "agents", "outputStyles")  # plugin manifest keys naming paths this script does not follow
SCRIPT_EXT = r"(?:py|sh|js|mjs|cjs|ts|ps1|cmd|bat|rb|pl)"
NAME_RE = re.compile(r"[\w.:@/+-]{1,%d}" % NAME_MAX)
STAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}(?::?\d{2})?)?")
WIN_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
# a hook command that is not POSIX shell syntax, or that this script cannot tell from it
NON_POSIX_RE = re.compile(r"%\w+%|\$env:|\\[^\s\"'\\]|^\s*(?:powershell|pwsh|cmd)(?:\.exe)?\b", re.I)
IMPORT_RE = re.compile(r"(?<![\w`@/\\.:])@((?:\\ |[^\s`'\"<>()\[\]{}|*?])+)")


class InputError(Exception):
    """The command line or an input file cannot be used. main() prints the message and exits 2."""


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
    return value if isinstance(value, (str, int, float, bool)) and len(str(value)) <= MAX_SCALAR else f"({type(value).__name__})"


def same_path(a, b) -> bool:
    try:
        return os.path.normcase(str(pathlib.Path(a).resolve())) == os.path.normcase(str(pathlib.Path(b).resolve()))
    except (OSError, RuntimeError, ValueError):
        return False


class Scan:
    """What one run reads: the problems it meets, and the reads it declines outside --home and --project."""

    def __init__(self, roots, confine: bool = False, user_home=None, extra_files=()):
        self.roots = []
        for root in roots:
            try:
                self.roots.append(pathlib.Path(root).resolve())
            except (OSError, RuntimeError):
                pass
        self.confine, self.user_home = confine, user_home
        self.extra = {os.path.normcase(str(pathlib.Path(p).resolve())) for p in extra_files}
        self.unreadable: list = []
        self.skipped_outside: list = []
        self.ancestors_skipped = False
        self.unresolved_imports = 0

    def inside(self, path: pathlib.Path) -> bool:
        """Whether the path, with symlinks followed, lies in --home or --project (or is a file named by --user-config)."""
        try:
            real = path.resolve()
        except (OSError, RuntimeError):
            return False
        return (os.path.normcase(str(real)) in self.extra
                or any(real == root or root in real.parents for root in self.roots))

    def allowed(self, path: pathlib.Path) -> bool:
        if not self.confine or self.inside(path):
            return True
        self.skipped_outside.append(str(path))
        return False

    def is_file(self, path: pathlib.Path) -> bool:
        return self.allowed(path) and path.is_file()

    def is_dir(self, path: pathlib.Path) -> bool:
        return self.allowed(path) and path.is_dir()

    def read(self, path: pathlib.Path) -> str:
        if not self.allowed(path):
            return ""
        try:
            return path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            self.unreadable.append(f"{path}: {type(exc).__name__}")
            return ""

    def read_json(self, path: pathlib.Path) -> dict:
        """A JSON object from disk, or {} with the reason recorded. A missing file is not an error."""
        if not self.is_file(path):
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError) as exc:
            self.unreadable.append(f"{path}: {type(exc).__name__}")
            return {}
        if not isinstance(data, dict):
            self.unreadable.append(f"{path}: expected a JSON object, found {type(data).__name__}")
            return {}
        return data


def parse_frontmatter(text: str) -> dict:
    """Reads the frontmatter block with a line-based reader that covers a subset of YAML, not all of it.

    Returns {meta: safe fields, other: names of other fields, body, notes, present}. `notes` says, by
    field name and never by value, what was seen but not interpreted.

    The rule is structural: a line that starts in the first column begins a new
    top-level entry, whatever it looks like; an indented line belongs to the entry
    above it. Values are kept only for entries whose key is in SAFE_FIELDS, so a
    block under any other key (quoted, commented, oddly spaced) is never copied.
    Under a safe key, list items are kept; free continuation text is kept only for
    the prose fields, so a mapping nested under `tools:` or `skills:` is dropped.
    """
    if not text.startswith("---"):
        return {"meta": {}, "other": [], "body": text, "notes": [], "present": False}
    end = text.find("\n---", 3)
    if end < 0:
        return {"meta": {}, "other": [], "body": text, "present": False,
                "notes": ["the frontmatter block is never closed with ---: none of it was read"]}
    data, other, key, notes, stray = {}, [], None, [], 0

    def note(message: str) -> None:
        if message not in notes:
            notes.append(message)

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
                        note(f"{key}: an inline mapping was not interpreted")
                    elif val.startswith("["):
                        note(f"{key}: an inline list is kept as written, not split into items")
                    elif val[:1] in ("&", "*", "!"):
                        note(f"{key}: a YAML anchor, alias or tag was not resolved")
                if val in (">", "|", ">-", "|-"):
                    note(f"{key}: a block scalar; its lines are joined with spaces" if key in TEXT_FIELDS
                         else f"{key}: a block scalar was not interpreted")
                data[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
            else:
                key = None
                label = re.match(r"^[\"']?([A-Za-z][A-Za-z0-9_.-]{0,40})[\"']?\s*:", line)
                if label:
                    other.append(label.group(1))
                elif not item.startswith("#"):
                    stray += 1
        elif key and is_list_item:
            entry = item[2:].strip().strip("\"'")
            if key in TEXT_FIELDS or not re.search(r":\s|:$|^\{", entry):  # a list of mappings is not a list of names
                data[key] = f"{data[key]}, {entry}" if data[key] else entry
            else:
                note(f"{key}: a list of mappings was not interpreted")
        elif key in TEXT_FIELDS:
            data[key] = (data[key] + " " + item).strip()
        elif key:
            note(f"{key}: indented lines under it (a nested mapping or a block) were not interpreted")
    if stray:
        note(f"{stray} line(s) in the block were not 'key: value' entries and were not read")
    for k, v in data.items():
        if len(v) > MAX_VALUE:
            note(f"{k}: the value was cut at {MAX_VALUE} characters")
    return {"meta": {k: v[:MAX_VALUE] for k, v in data.items()}, "other": other, "body": text[end + 4:],
            "notes": notes, "present": True}


def frontmatter(text: str):
    """(safe fields, names of other fields, body); see parse_frontmatter for the rule and for what was not interpreted."""
    parsed = parse_frontmatter(text)
    return parsed["meta"], parsed["other"], parsed["body"]


# ---------------------------------------------------------------- pieces on disk

def qualify(label: str, name: str) -> str:
    """The name a plugin piece is invoked by: `plugin:name`, without doubling a prefix the name already has."""
    if not label.startswith("plugin:"):
        return name
    prefix = label[len("plugin:"):]
    return name if name.startswith(prefix + ":") else f"{prefix}:{name}"


def instruction_mode(settings: list) -> dict:
    """The AGENTS.md mode. Of the files this script sees, Claude Code honors the user-level settings file only."""
    result = {"value": INSTRUCTION_MODES[0], "source": "default", "note": None}
    for label, _, data in settings:
        chosen = as_dict(as_dict(as_dict(data.get("pluginConfigs")).get(INSTRUCTION_PLUGIN_ID)).get("options")).get("instructionFiles")
        if chosen is None:
            continue
        if label != "user":
            result["note"] = f"{label} settings name an instruction mode; Claude Code ignores it there"
        elif isinstance(chosen, str) and chosen in INSTRUCTION_MODES:
            result.update(value=chosen, source="user settings (pluginConfigs)", note=None)
        else:
            result["note"] = "the user settings name an instruction mode this script does not know; the default was assumed"
    return result


def import_target(ref: str, base: pathlib.Path, scan: Scan):
    """The file an `@path` import names, or None when it cannot be resolved here (counted, never guessed)."""
    ref = re.sub(r"[.,;:!?]+$", "", ref.replace("\\ ", " "))
    if ref == "~" or ref.startswith(("~/", "~\\")):
        if scan.user_home is None:
            scan.unresolved_imports += 1
            return None
        return scan.user_home / ref[2:]
    if ref.startswith("~"):
        scan.unresolved_imports += 1
        return None
    if WIN_DRIVE_RE.match(ref) and os.name != "nt":
        scan.unresolved_imports += 1
        return None
    target = pathlib.Path(ref)
    return target if target.is_absolute() else base / target


def ancestor_dirs(project: pathlib.Path) -> list:
    """The project directory and every directory above it, outermost first: where instruction files are searched."""
    return list(reversed([project, *project.parents]))


def instruction_files(home: pathlib.Path, project: pathlib.Path, scan: Scan, mode: str = INSTRUCTION_MODES[0]) -> list:
    """Instruction files that load at session start, with the files they import.

    In the default mode an AGENTS.md found on its own beside a CLAUDE.md is listed with
    `loads: "only if no CLAUDE.md is found"`, since Claude Code reads it only in that case;
    the other modes change that (see `instruction_mode`). One that a CLAUDE.md imports loads with that file.
    """
    roots = [(home / "CLAUDE.md", "user")]
    if scan.confine:
        scan.ancestors_skipped = True
        directories = [project]
    else:
        directories = ancestor_dirs(project)
    for d in directories:
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md", ".claude/AGENTS.md"):
            p = d / name
            if p != home / "CLAUDE.md":
                roots.append((p, "project" if d == project else "ancestor"))
    roots.sort(key=lambda r: r[0].name == "AGENTS.md")  # imports of AGENTS.md are met before the bare file
    out, seen = [], set()
    has_claude_md = any(p.is_file() and p.name != "AGENTS.md" and scope != "user"
                        for p, scope in roots if not scan.confine or scan.inside(p))

    def standalone_loads(path: pathlib.Path) -> str:
        if mode == "managed-only":
            return "not loaded at launch (instruction mode managed-only)"
        if path.name == "AGENTS.md":
            if mode == "claude-md":
                return "not loaded (instruction mode claude-md)"
            if mode == INSTRUCTION_MODES[0] and has_claude_md:
                return "only if no CLAUDE.md is found"
        return "session start"

    def add(path: pathlib.Path, scope: str, via: str, depth: int) -> None:
        try:
            key = path.resolve()
        except (OSError, RuntimeError):
            return
        if key in seen or not scan.is_file(path):
            return
        seen.add(key)
        text = scan.read(path)
        loads = standalone_loads(path) if not via else "session start"
        out.append({"path": str(path), "scope": scope, "imported_by": via, "chars": len(text),
                    "lines": text.count("\n") + 1, "est_tokens": est_tokens(len(text)), "loads": loads,
                    "external": not scan.inside(path)})
        if depth >= IMPORT_DEPTH or loads != "session start":
            return
        body = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))
        for ref in IMPORT_RE.findall(body):
            target = import_target(ref, path.parent, scan)
            if target is not None:
                add(target, scope, str(path), depth + 1)

    for path, scope in roots:
        add(path, scope, "", 0)
    return out


def settings_files(home: pathlib.Path, project: pathlib.Path, scan: Scan) -> list:
    """(scope, path, parsed object) for each settings file that exists, lowest precedence first."""
    found, seen = [], set()
    for label, path in (("user", home / "settings.json"), ("project", project / ".claude" / "settings.json"),
                        ("local", project / ".claude" / "settings.local.json")):
        if not scan.is_file(path) or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        found.append((label, path, scan.read_json(path)))
    return found


def plugin_layout(base: pathlib.Path, scan: Scan) -> dict:
    """How a plugin folder holds its skills, and which manifest keys name paths this script does not follow."""
    manifest = scan.read_json(base / ".claude-plugin" / "plugin.json")
    declares = [k for k in MANIFEST_PATH_KEYS if k in manifest]
    has_folder = scan.is_dir(base / "skills")
    root_skill = scan.is_file(base / "SKILL.md") and not has_folder and "skills" not in manifest
    return {"layout": "SKILL.md at the plugin root" if root_skill else "skills/ folder" if has_folder else "no skills in the default places",
            "root_skill": root_skill, "manifest_paths_not_followed": declares}


def plugin_inventory(home: pathlib.Path, project: pathlib.Path, settings: list, scan: Scan):
    """(records for the output, [(label, folder, root_skill)] for the plugins that count in this setup).

    A plugin counts when the effective settings enable it (a later file replaces an earlier one, so a
    `false` above a `true` disables it) and an install entry applies to this project: scope user or
    managed always; scope project or local only when its projectPath is this project.
    """
    enabled, decided = {}, {}
    for label, _, data in settings:  # lowest precedence first: a later file replaces an earlier one
        for key, value in as_dict(data.get("enabledPlugins")).items():
            enabled[key], decided[key] = bool(value), label
    installed = scan.read_json(home / "plugins" / "installed_plugins.json")
    records, bases, seen_ids, seen_paths = [], [], set(), set()
    for key, entries in as_dict(installed.get("plugins")).items():
        seen_ids.add(key)
        name = key.split("@")[0]
        record = {"id": clean_name(key), "name": clean_name(name), "enabled": enabled.get(key, False),
                  "decided_by": decided.get(key, "no enabledPlugins entry"), "installs": []}
        records.append(record)
        if not record["enabled"]:
            continue
        for entry in (entries if isinstance(entries, list) else [entries]):
            e = as_dict(entry)
            scope = e.get("scope") if isinstance(e.get("scope"), str) else "(missing)"
            where = e.get("installPath")
            install = {"scope": clean_name(scope), "applies": False, "reason": ""}
            if scope in ("project", "local"):
                if not isinstance(e.get("projectPath"), str) or not e["projectPath"]:
                    install["reason"] = "install entry of project scope without a projectPath"
                elif same_path(e["projectPath"], project):
                    install["applies"] = True
                else:
                    install["reason"] = "installed for another project"
            elif scope in ("user", "managed"):
                install["applies"] = True
            else:
                install["reason"] = "unrecognized install scope"
            if install["applies"]:
                folder = pathlib.Path(where) if isinstance(where, str) and where else None
                if folder is None or not scan.is_dir(folder):
                    install.update(applies=False, reason="install path missing, not a folder, or outside --home and --project")
                elif folder.resolve() in seen_paths:
                    install.update(applies=False, reason="same folder as another install entry")
                else:
                    seen_paths.add(folder.resolve())
                    layout = plugin_layout(folder, scan)
                    install.update(install_path=str(folder), layout=layout["layout"],
                                   manifest_paths_not_followed=layout["manifest_paths_not_followed"])
                    bases.append((f"plugin:{name}", folder, layout["root_skill"]))
            record["installs"].append(install)
    for key, value in enabled.items():
        if value and key not in seen_ids:
            records.append({"id": clean_name(key), "name": clean_name(key.split("@")[0]), "enabled": True,
                            "decided_by": decided[key], "installs": [], "note": "enabled in settings, no install record"})
    return records, bases


def scopes(home: pathlib.Path, project: pathlib.Path, plugin_bases: list) -> list:
    """(label, directory, plugin has its skill at the root) for every place that can hold skills, agents, commands, rules, styles."""
    found = [("user", home, False)]
    if (project / ".claude").is_dir() and not same_path(project / ".claude", home):
        found.append(("project", project / ".claude", False))
    return found + plugin_bases


def bundled_files(folder: pathlib.Path, skill: pathlib.Path, scan: Scan) -> list:
    try:
        return [p for p in folder.rglob("*")
                if p.is_file() and p != skill and not {".git", "__pycache__"} & set(p.relative_to(folder).parts)]
    except OSError as exc:
        scan.unreadable.append(f"{folder}: {type(exc).__name__} while listing files")
        return []


def skill_record(skill: pathlib.Path, label: str, overrides: dict, scan: Scan, cap: int = LISTING_CAP,
                 fallback_name: str = "") -> dict:
    parsed = parse_frontmatter(scan.read(skill))
    meta, other, body, notes = parsed["meta"], parsed["other"], parsed["body"], list(parsed["notes"])
    if not parsed["present"] and not notes:
        notes.append("no frontmatter: the file does not begin with ---, so Claude Code reads the whole file as content")
    name = meta.get("name") or fallback_name or skill.parent.name
    description, source = meta.get("description", ""), "frontmatter"
    if not description:  # documented fallback: the first non-empty line of the content
        description = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")[:MAX_VALUE]
        source = "first non-empty body line (documented fallback)" if description else "none"
    listing = (description + " " + meta.get("when_to_use", "")).strip()
    # skillOverrides applies to user and project skills; plugin skills are managed through /plugin.
    state, override = "on", None if label.startswith("plugin:") else overrides.get(name)
    if override is not None:
        if isinstance(override, str) and override in SKILL_STATES:
            state = override
        else:
            notes.append("skillOverrides holds a value this script does not recognize for this skill; it was treated as on")
    if meta.get("disable-model-invocation", "").lower() == "true" and state == "on":
        state = "user-invocable-only"
    listed = {"on": min(len(listing), cap), "name-only": len(name)}.get(state, 0)
    bundled = bundled_files(skill.parent, skill, scan)
    return {"name": name, "qualified": qualify(label, name), "scope": label, "path": str(skill), "frontmatter": meta,
            "other_fields": other, "parse_notes": notes, "description_source": source,
            "visibility": state, "model_invocable": state in ("on", "name-only"),
            "listing_chars": len(listing), "listing_truncated": state == "on" and len(listing) > cap,
            "always_est_tokens": est_tokens(listed),
            "body_lines": body.count("\n") + 1, "on_invoke_est_tokens": est_tokens(len(body)),
            "bundled_files": len(bundled)}


def agent_record(agent: pathlib.Path, label: str, scan: Scan) -> dict:
    parsed = parse_frontmatter(scan.read(agent))
    meta, other, body, notes = parsed["meta"], parsed["other"], parsed["body"], list(parsed["notes"])
    if not parsed["present"] and not notes:
        notes.append("no frontmatter: the file does not begin with ---")
    name = meta.get("name") or agent.stem
    return {"name": name, "qualified": qualify(label, name), "scope": label, "path": str(agent), "frontmatter": meta,
            "other_fields": other, "parse_notes": notes, "model": meta.get("model", "(inherits)"),
            "effort": meta.get("effort", "(unset)"), "tools": meta.get("tools", "(all)"),
            "listing_chars": len(meta.get("description", "")),
            "always_est_tokens": est_tokens(len(meta.get("description", ""))),
            "body_lines": body.count("\n") + 1, "on_spawn_est_tokens": est_tokens(len(body))}


def markdown_pieces(scope_list: list, overrides: dict, scan: Scan, cap: int = LISTING_CAP) -> dict:
    kinds = {"skills": [], "agents": [], "commands": [], "rules": [], "output_styles": []}
    for label, base, root_skill in scope_list:
        for skill in sorted((base / "skills").glob("*/SKILL.md")):
            kinds["skills"].append(skill_record(skill, label, overrides, scan, cap))
        if root_skill:  # a plugin with SKILL.md at its root: one skill, named by `name` or else by the plugin
            kinds["skills"].append(skill_record(base / "SKILL.md", label, overrides, scan, cap, fallback_name=label[len("plugin:"):]))
        for agent in sorted((base / "agents").rglob("*.md")):
            record = agent_record(agent, label, scan)
            if record["frontmatter"].get("name") or record["frontmatter"].get("description"):
                kinds["agents"].append(record)
        for kind, sub in (("commands", "commands"), ("rules", "rules"), ("output_styles", "output-styles")):
            for path in sorted((base / sub).rglob("*.md")):
                text = scan.read(path)
                parsed = parse_frontmatter(text)
                meta = parsed["meta"]
                item = {"name": meta.get("name") or path.stem, "scope": label, "path": str(path),
                        "chars": len(text), "est_tokens": est_tokens(len(text)), "frontmatter": meta, "other_fields": parsed["other"],
                        "parse_notes": parsed["notes"]}
                if kind == "rules":
                    item["loads"] = "when a matching file is read" if "paths" in meta else "session start"
                kinds[kind].append(item)
    return kinds


# ---------------------------------------------------------------- hooks

def split_non_posix(command: str):
    """Words of a command split on spaces outside double quotes, with no escape processing. (words, quotes balanced)."""
    words, current, quoted = [], [], False
    for ch in command:
        if ch == '"':
            quoted = not quoted
        elif ch.isspace() and not quoted:
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        words.append("".join(current))
    return words, not quoted


def hook_script_paths(command: str, home: pathlib.Path, project: pathlib.Path, user_home=None, scan=None) -> dict:
    """Script files a hook command names, sorted into what can be checked and what cannot.

    {missing: resolved paths that do not exist; missing_relative: relative paths that do not exist
    under the project directory (a hook may run from another working directory, so these are weaker);
    unresolved: names whose base, shell syntax or variables are not known here; note: why parsing stopped short}.
    A path is checked only when its variables (CLAUDE_PROJECT_DIR, HOME, USERPROFILE, `~`) have a known value
    and its syntax is one this script reads: POSIX shell words, or Windows words with absolute paths on Windows.
    """
    result = {"missing": [], "missing_relative": [], "unresolved": [], "note": ""}
    if NON_POSIX_RE.search(command):
        words, balanced = split_non_posix(command)
        result["note"] = "Windows or PowerShell syntax: only absolute paths and known variables are checked"
    else:
        try:
            words, balanced = shlex.split(command), True
        except ValueError:
            return {**result, "note": "unbalanced quotes: the command was not interpreted"}
    if not balanced:
        return {**result, "note": "unbalanced quotes: the command was not interpreted"}
    known = {"CLAUDE_PROJECT_DIR": project}
    if user_home is not None:
        known.update(HOME=user_home, USERPROFILE=user_home)
    for word in words:
        if not re.search(r"\." + SCRIPT_EXT + r"$", word, re.I):
            continue
        token = word
        for var, target in known.items():
            token = re.sub(r"\$\{%s\}|\$%s(?![A-Za-z0-9_])|%%%s%%" % (var, var, var), lambda _m, t=target: t.as_posix(), token)
        if token == "~" or token.startswith(("~/", "~\\")):
            rest = token[2:]
            if user_home is not None:
                token = (user_home / rest).as_posix()
            elif rest.replace("\\", "/").startswith(".claude/"):
                token = (home / rest.replace("\\", "/")[len(".claude/"):]).as_posix()  # --home stands in for ~/.claude
            else:
                result["unresolved"].append(word)
                continue
        if re.search(r"[$%`*?\[{]", token) or token.startswith("~"):
            result["unresolved"].append(word)
            continue
        relative = False
        if WIN_DRIVE_RE.match(token) or token.startswith("\\\\"):
            if os.name != "nt":
                result["unresolved"].append(word)
                continue
            path = pathlib.Path(token)
        elif token.startswith("/"):
            if os.name == "nt":  # a Git Bash style path, or a path on the current drive: the base is not known
                result["unresolved"].append(word)
                continue
            path = pathlib.Path(token)
        else:
            if "\\" in token and os.name != "nt":
                result["unresolved"].append(word)
                continue
            relative, path = True, project / token.replace("\\", "/")
        if scan is not None and scan.confine and not scan.inside(path):
            result["unresolved"].append(word)
            continue
        if not path.exists():
            result["missing_relative" if relative else "missing"].append(token)
    return result


def missing_scripts(command: str, home: pathlib.Path, project: pathlib.Path) -> list:
    """Script files a hook command names that are not on disk (relative ones judged against the project).
    Paths it cannot resolve are left out, not guessed. `~` is the directory holding --home when that is named `.claude`."""
    paths = hook_script_paths(command, home, project, home.parent if home.name == ".claude" else None)
    return paths["missing"] + paths["missing_relative"]


def settings_view(home: pathlib.Path, project: pathlib.Path, settings: list, scan: Scan, user_config: pathlib.Path) -> dict:
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
        plugins = as_dict(data.get("enabledPlugins"))
        view["files"].append({
            "scope": label, "path": str(path), "keys": sorted(data), "values": values,
            "env_names": sorted(as_dict(data.get("env"))),
            "permissions": {k: (len(v) if isinstance(v, list) else scalar(v) if k == "defaultMode" else f"({type(v).__name__})")
                            for k, v in perms.items()},
            "permission_rules": {k: [r[:MAX_RULE] for r in v if isinstance(r, str)][:MAX_RULES]
                                 for k, v in perms.items() if k in ("allow", "ask", "deny") and isinstance(v, list)},
            "enabledPlugins": sorted(k for k, v in plugins.items() if v),
            "disabledPlugins": sorted(k for k, v in plugins.items() if not v),
            "skillOverrides": {clean_name(k): (v if isinstance(v, str) and v in SKILL_STATES else "(other)")
                               for k, v in as_dict(data.get("skillOverrides")).items()}})
        for event, groups in as_dict(data.get("hooks")).items():
            for group in as_list(groups):
                group = as_dict(group)
                for hook in as_list(group.get("hooks")):
                    hook = as_dict(hook)
                    cmd = hook.get("command") if isinstance(hook.get("command"), str) else ""
                    known = {"command", "type", "timeout"} | SAFE_HOOK_OPTIONS
                    paths = hook_script_paths(cmd, home, project, scan.user_home, scan)
                    view["hooks"].append({
                        "scope": label, "event": str(event), "matcher": scalar(group.get("matcher", "")),
                        "type": scalar(hook.get("type", "command")), "command": cmd, "timeout": scalar(hook.get("timeout")),
                        "options": {k: scalar(hook[k]) for k in SAFE_HOOK_OPTIONS if k in hook},
                        "other_options": sorted(k for k in hook if k not in known),
                        "scripts_missing": paths["missing"],
                        "scripts_missing_relative_to_project": paths["missing_relative"],
                        "scripts_unresolved": paths["unresolved"], "path_check_note": paths["note"]})
    config = scan.read_json(user_config)
    sources = [("project", as_dict(scan.read_json(project / ".mcp.json").get("mcpServers"))),
               ("user", as_dict(config.get("mcpServers")))]
    for key, conf in as_dict(config.get("projects")).items():
        if same_path(key, project):
            sources.append(("local", as_dict(as_dict(conf).get("mcpServers"))))
    for label, servers in sources:
        for name, conf in servers.items():
            view["mcp_servers"].append({"scope": label, "name": clean_name(name), "transport": scalar(as_dict(conf).get("type", "stdio"))})
    return view


def overlaps(pieces: dict, limit: int = TOP_OVERLAPS) -> list:
    """Pairs of routing descriptions that share vocabulary. Candidates for a human or model to judge.

    Words that appear in more than a third of the descriptions say nothing about any one
    of them, so they are ignored. That adapts to the setup's own language and vocabulary
    without a stop-word list. Thresholds are the OVERLAP_* constants.
    """
    items = []
    word_re = r"[^\W\d_]{%d,}" % OVERLAP_MIN_WORD_CHARS
    for kind in ("skills", "agents"):
        for p in pieces[kind]:
            if kind == "skills" and p["visibility"] != "on":
                continue
            fm = p["frontmatter"]
            words = set(re.findall(word_re, (fm.get("description", "") + " " + fm.get("when_to_use", "")).lower()))
            items.append((f"{kind[:-1]}:{p['qualified']}", words))
    seen_in = collections.Counter(w for _, words in items for w in words)
    common = {w for w, n in seen_in.items() if len(items) >= OVERLAP_COMMON_MIN_PIECES and n > len(items) * OVERLAP_COMMON_SHARE}
    items = [(name, words - common) for name, words in items if len(words - common) >= OVERLAP_MIN_WORDS]
    pairs = []
    for i, (a, wa) in enumerate(items):
        for b, wb in items[i + 1:]:
            score = len(wa & wb) / len(wa | wb)
            if score >= OVERLAP_MIN_JACCARD:
                pairs.append({"a": a, "b": b, "jaccard": round(score, 2), "shared": sorted(wa & wb)[:OVERLAP_SHARED_SHOWN]})
    return sorted(pairs, key=lambda x: -x["jaccard"])[:limit]


# ---------------------------------------------------------------- session history

def parse_stamp(value):
    """(an aware datetime or None, whether the stamp carried no offset). A stamp without an offset is read as UTC."""
    m = STAMP_RE.fullmatch(value) if isinstance(value, str) else None
    if not m:
        return None, False
    year, month, day, hour, minute, second, fraction, zone = m.groups()
    try:
        if zone in (None, "Z"):
            tz = dt.timezone.utc
        else:
            digits = zone[1:].replace(":", "")
            offset = dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
            tz = dt.timezone(-offset if zone[0] == "-" else offset)
        when = dt.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second),
                           int((fraction or "0")[:6].ljust(6, "0")), tzinfo=tz)
    except ValueError:
        return None, False
    return when, zone is None


def wholly_before(path: pathlib.Path, cutoff: dt.datetime) -> bool:
    """True when the end of a transcript already shows that every row is older than the window.

    Rows are appended in time order, so the last row with a readable timestamp bounds the file. The file's
    modification time is not trusted on its own: a copied or restored history can carry an old one.
    """
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - TAIL_BYTES))
            chunk = handle.read()
    except OSError:
        return False
    for line in reversed(chunk.splitlines()):
        if b'"timestamp"' not in line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        when, _ = parse_stamp(row.get("timestamp")) if isinstance(row, dict) else (None, False)
        if when is not None:
            return when < cutoff
    return False


def attribute(invoked, pieces: list):
    """Match invoked names to pieces. Returns (qualified names used, names matching nothing here, ambiguous bare names).

    A qualified name (`plugin:skill`) reaches only the piece with that qualified name. A bare name reaches the
    piece of that name when there is one, and every piece of that name when there are several (the benefit
    of the doubt: nothing is called unused because of an ambiguity), listing the name as ambiguous.
    """
    used, unmatched, ambiguous = set(), set(), set()
    for name in invoked:
        exact = [p for p in pieces if p["qualified"] == name]
        if exact:
            used.update(p["qualified"] for p in exact)
        elif ":" not in name:
            bare = [p for p in pieces if p["name"] == name]
            if bare:
                used.update(p["qualified"] for p in bare)
                if len(bare) > 1:
                    ambiguous.add(name)
            else:
                unmatched.add(name)
        else:
            unmatched.add(name)
    return used, unmatched, ambiguous


def usage(home: pathlib.Path, days: int, scan: Scan) -> dict:
    if days <= 0 or not scan.is_dir(home / "projects"):
        return {}
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    cutoff_epoch = cutoff.timestamp()
    tools, skills, agents, effort, slash = (collections.Counter() for _ in range(5))
    result_chars = collections.Counter()
    sessions = {"main": set(), "subagent": set()}
    messages: dict = {}   # message id -> (scope, model, usage); a resumed session repeats rows, so each id counts once
    rows_seen: set = set()  # row uuids, for the same reason
    tool_of: dict = {}
    order: dict = collections.defaultdict(list)  # main-session file -> [(time, message id)] in the order first seen
    runs = collections.Counter()                 # subagent runs per agent type
    skipped = collections.Counter()
    coverage = collections.Counter()
    root = home / "projects"
    files = [(p, "main") for p in root.glob("*/*.jsonl")] + [(p, "subagent") for p in root.glob("*/*/subagents/*.jsonl")]

    def agent_type_of(path: pathlib.Path) -> str:
        """Claude Code writes a small description beside each subagent transcript; it names the agent type."""
        for suffix in (".meta.json", ".json"):
            sidecar = path.with_suffix(suffix)
            if not scan.allowed(sidecar):  # a link here can lead out of --home and --project
                continue
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError):
                continue
            if isinstance(meta, dict) and isinstance(meta.get("agentType"), str):
                return clean_name(meta["agentType"])
        return "(unknown)"

    def take(row: dict, scope: str, fallback_session: str, agent: str) -> None:
        when, naive = parse_stamp(row.get("timestamp"))
        if when is None:
            skipped["rows without a readable timestamp"] += 1
            return
        coverage["naive_timestamps_read_as_utc"] += naive
        if when < cutoff:
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
                        order[fallback_session].append((when, mid))
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

    coverage["files_found"] = len(files)
    for path, scope in files:
        if scan.confine and not scan.inside(path):
            coverage["files_outside_scope_skipped"] += 1
            continue
        try:
            if path.stat().st_mtime < cutoff_epoch and wholly_before(path, cutoff):
                coverage["files_wholly_before_window"] += 1
                continue
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError as exc:
            scan.unreadable.append(f"{path}: {type(exc).__name__}")
            continue
        coverage["files_read"] += 1
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
        scan.unreadable.append(f"{root}: {count} {reason}, not counted")

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

    # A cache rebuild: a request that wrote most of its prompt to the cache although the request before it,
    # in the same session, already held more than half of that prompt. The context was there and was paid for again.
    # The history records no reason, so the cause given for each is an inference from sizes, gaps and model names.
    rebuilds = collections.defaultdict(lambda: {"count": 0, "tokens_rewritten": 0})
    lifetimes = collections.Counter()
    considered = 0
    for sequence in order.values():
        prev = None
        for when, mid in sorted(sequence, key=lambda pair: pair[0]):
            considered += 1
            _, model, use, _ = messages[mid]
            written, prompt = num(use.get("cache_creation_input_tokens")), prompt_of(use)
            split = as_dict(use.get("cache_creation"))
            long_lived = num(split.get("ephemeral_1h_input_tokens")) > 0
            if written:
                lifetimes["long" if long_lived else "short"] += written
            if prev and prompt and written > prompt * REBUILD_SHARE and prev[2] > prompt * REBUILD_SHARE:
                gap = (when - prev[0]).total_seconds()
                if prompt < prev[2] * COMPACTION_SHRINK:
                    cause = "after the context was compacted or cleared"
                elif gap > (CACHE_LONG if long_lived else CACHE_SHORT):
                    cause = "after a pause longer than the cache lifetime"
                elif model != prev[1]:
                    cause = "after a model switch"
                else:
                    cause = "other (a change to tools or settings, or a cause the history does not show)"
                rebuilds[cause]["count"] += 1
                rebuilds[cause]["tokens_rewritten"] += written
            prev = (when, model, prompt)

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
        "window_days": days, "scope": "recognized transcripts under one config tree (every project folder in it)",
        "transcript_root": str(root), "coverage": dict(coverage),
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
                                         "when the request before it in the same session held more than half of that prompt; "
                                         "one cause is given per rebuild, checked in the order compaction, pause, model switch",
                           "basis": "inference from request sizes, the time between requests and the model name; "
                                    "the history does not record why a cache was rebuilt, so each cause is a hypothesis",
                           "main_requests_considered": considered,
                           "by_cause": {k: dict(v) for k, v in sorted(rebuilds.items(), key=lambda kv: -kv[1]["tokens_rewritten"])}},
        "main_cache_write_tokens_by_lifetime": dict(lifetimes),
        "tool_result_chars": dict(result_chars.most_common(TOP_TOOL_RESULTS)), "requests_by_model_and_effort": dict(effort.most_common())}


# ---------------------------------------------------------------- assembly

def resolve_user_home(home: pathlib.Path, env_dir):
    """The audited user's home directory, or None when it cannot be told from --home."""
    try:
        real = pathlib.Path.home()
    except (RuntimeError, KeyError, OSError):
        real = None
    if real is not None and ((env_dir and same_path(home, pathlib.Path(env_dir).expanduser())) or same_path(home, real / ".claude")):
        return real
    return home.parent if home.name == ".claude" else None


def resolve_user_config(home: pathlib.Path, explicit, env_dir):
    """(path of the user-level .claude.json, the rule that chose it); see the module docstring."""
    if explicit:
        return pathlib.Path(explicit).expanduser(), "--user-config"
    if env_dir and same_path(home, pathlib.Path(env_dir).expanduser()):
        return home / ".claude.json", "inside --home, which is $CLAUDE_CONFIG_DIR (documented location)"
    if home.name == ".claude":
        return home.parent / ".claude.json", "beside --home, which is named .claude (assumed default layout, ~/.claude.json)"
    return home / ".claude.json", "inside --home, which is not named .claude (assumed config-directory layout)"


def effective_listing_cap(settings: list) -> dict:
    cap = {"chars": LISTING_CAP, "source": "documented default (kb/harness.json)"}
    for label, _, data in settings:  # `skillListingMaxDescChars` may be set in any settings file; the highest-precedence one wins
        value = data.get("skillListingMaxDescChars")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            cap = {"chars": value, "source": f"skillListingMaxDescChars in {label} settings"}
    return cap


def build(home: pathlib.Path, project: pathlib.Path, days: int, *, confine: bool = False,
          user_config=None, user_home="auto") -> dict:
    """Measure a setup. `user_config` is (path, basis) or None to resolve it from --home; `user_home` None means unknown."""
    if user_home == "auto":
        user_home = home.parent if home.name == ".claude" else None
    if user_config is None:
        user_config = resolve_user_config(home, None, None)
    config_path, config_basis = user_config
    scan = Scan([home, project], confine, user_home, extra_files=[config_path] if config_basis == "--user-config" else ())
    settings_raw = settings_files(home, project, scan)
    overrides: dict = {}
    for _, _, data in settings_raw:  # lowest precedence first, so the highest-precedence value stays
        overrides.update(as_dict(data.get("skillOverrides")))
    mode = instruction_mode(settings_raw)
    cap = effective_listing_cap(settings_raw)
    instr = instruction_files(home, project, scan, mode["value"])
    plugins, plugin_bases = plugin_inventory(home, project, settings_raw, scan)
    pieces = markdown_pieces(scopes(home, project, plugin_bases), overrides, scan, cap["chars"])
    if mode["value"] == "managed-only":
        for rule in pieces["rules"]:
            if rule["loads"] == "session start":
                rule["loads"] = "not loaded at launch (instruction mode managed-only)"
    settings = settings_view(home, project, settings_raw, scan, config_path)
    hist = usage(home, days, scan)
    active_style = next((f["values"]["outputStyle"] for f in reversed(settings["files"]) if f["values"].get("outputStyle")), None)
    style_tokens = sum(s["est_tokens"] for s in pieces["output_styles"] if active_style and s["name"].lower() == str(active_style).lower())
    fixed = {
        "instruction_files": sum(f["est_tokens"] for f in instr if f["loads"] == "session start"),
        "rules_without_paths": sum(r["est_tokens"] for r in pieces["rules"] if r.get("loads") == "session start"),
        "skill_listing": sum(s["always_est_tokens"] for s in pieces["skills"]),
        "agent_listing": sum(a["always_est_tokens"] for a in pieces["agents"]),
        "active_output_style": style_tokens}
    spawns = hist.get("agent_spawns", {})
    never = {}
    spawned_elsewhere: list = []
    if hist:
        used_skills, _, skill_amb = attribute({**hist["skill_invocations"], **hist["typed_commands"]}, pieces["skills"])
        used_agents, agent_unmatched, agent_amb = attribute(spawns, pieces["agents"])
        matched = sum(n for a, n in spawns.items() if a not in agent_unmatched)
        hist["share_of_spawns_to_agents_defined_here"] = round(matched / sum(spawns.values()), 4) if spawns else None
        hist["attribution"] = ("by invocation name across every transcript read: a qualified name reaches only that plugin's piece; "
                               "a bare name reaches the piece of that name here, all of them when several share it")
        hist["attribution_ambiguous"] = {"skills": sorted(skill_amb), "agents": sorted(agent_amb)}
        never = {"skills": sorted(s["qualified"] for s in pieces["skills"] if s["model_invocable"] and s["qualified"] not in used_skills),
                 "agents": sorted(a["qualified"] for a in pieces["agents"] if a["qualified"] not in used_agents)}
        spawned_elsewhere = sorted(agent_unmatched)
    declared = [f"{p['name']} ({', '.join(i['manifest_paths_not_followed'])})"
                for p in plugins for i in p["installs"] if i.get("manifest_paths_not_followed")]
    not_measured = [
        "the built-in system prompt and tool definitions", "MCP tool definitions (see /context in a session)",
        "bundled skills", "auto memory (MEMORY.md)", "sessions from other machines",
        "managed settings and files passed with --settings (settings are read from the user, project and local files only)",
        "hooks defined by plugins or in skill and subagent frontmatter",
        "whether the skill listing exceeds its context budget (skillListingBudgetFraction is not applied)",
        "components a marketplace entry declares for a plugin (marketplace.json is not read)",
        "hook script paths whose base, shell syntax or variables are not known here (see scripts_unresolved)",
        "frontmatter is read by a line-based reader that covers a subset of YAML (see parse_notes on each piece)"]
    if declared:
        not_measured.append("plugin manifests that name paths for skills, commands, agents or output styles are not followed: " + "; ".join(declared))
    if any("claudeMdExcludes" in data for _, _, data in settings_raw):
        not_measured.append("claudeMdExcludes patterns are not applied: instruction files they exclude are still counted, so fixed context is an upper bound")
    if mode["note"]:
        not_measured.append("instruction mode: " + mode["note"])
    if scan.ancestors_skipped:
        not_measured.append("instruction files in directories above the project (--no-external-reads)")
    if scan.unresolved_imports:
        not_measured.append(f"{scan.unresolved_imports} instruction import(s) left unresolved: a `~` path with the user's home unknown, or a Windows drive path on another system")
    outside = sorted(set(scan.skipped_outside))
    if outside:
        not_measured.append(f"{len(outside)} file(s) outside --home and --project were not read (--no-external-reads)")
    hist_note = hist.get("coverage", {}).get("naive_timestamps_read_as_utc")
    if hist_note:
        not_measured.append(f"{hist_note} transcript row(s) had a timestamp without an offset and were read as UTC")
    for plugin in plugins:
        for install in plugin["installs"]:
            if plugin["enabled"] and not install["applies"]:
                not_measured.append(f"plugin {plugin['id']}: an install entry was not counted ({install['reason']})")
        if plugin.get("note"):
            not_measured.append(f"plugin {plugin['id']}: {plugin['note']}")
    return {
        "schema_version": SCHEMA_VERSION, "kind": "setup",
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "home": str(home), "project": str(project),
        "user_config": {"path": str(config_path), "basis": config_basis, "found": config_path.is_file() if scan.allowed(config_path) else False},
        "read_scope": {"confine_external_reads": confine, "skipped_outside_scope": outside[:SKIPPED_SHOWN]},
        "policy": POLICY,
        "estimate_note": f"est_tokens = characters / {CHARS_PER_TOKEN}; an estimate, not a tokenizer count",
        "not_measured": not_measured,
        "skill_listing_cap": cap, "instruction_mode": mode,
        "fixed_context_est_tokens": {**fixed, "total": sum(fixed.values())},
        "instruction_files": instr, **pieces, "plugins": plugins, "settings": settings,
        "description_overlaps": overlaps(pieces),
        "usage": hist, "never_invoked_in_window": never,
        "spawned_without_definition_here": spawned_elsewhere,
        "unreadable": scan.unreadable}


def summary(doc: dict) -> str:
    fx, use = doc["fixed_context_est_tokens"], doc["usage"]
    lines = [f"setup: {doc['home']}  project: {doc['project']}",
             f"fixed context every session (estimate, your files only): ~{fx['total']:,} tokens",
             "  " + "  ".join(f"{k}={v:,}" for k, v in fx.items() if k != "total"),
             f"pieces: {len(doc['instruction_files'])} instruction files, {len(doc['skills'])} skills, {len(doc['agents'])} agents, "
             f"{len(doc['commands'])} commands, {len(doc['rules'])} rules, {len(doc['settings']['hooks'])} hooks, "
             f"{len(doc['settings']['mcp_servers'])} MCP servers",
             f"plugins counted: {sum(1 for p in doc['plugins'] for i in p['installs'] if i['applies'])} of "
             f"{sum(1 for p in doc['plugins'] if p['enabled'])} enabled"]
    if doc["instruction_mode"]["source"] != "default":
        lines.append(f"instruction mode: {doc['instruction_mode']['value']} ({doc['instruction_mode']['source']})")
    restricted = sum(1 for s in doc["skills"] if s["visibility"] != "on")
    if restricted:
        lines.append(f"skills restricted by settings or frontmatter (not fully listed to the model): {restricted}")
    long_files = [f for f in doc["instruction_files"] if f["lines"] > LONG_FILE_LINES]
    if long_files:
        lines.append(f"instruction files over {LONG_FILE_LINES} lines: "
                     + ", ".join(f"{pathlib.Path(f['path']).name} ({f['lines']})" for f in long_files))
    hooks = doc["settings"]["hooks"]
    broken = [h for h in hooks if h["scripts_missing"]]
    if broken:
        lines.append(f"hooks naming a script that does not exist: {len(broken)}")
    relative = [h for h in hooks if h["scripts_missing_relative_to_project"]]
    if relative:
        lines.append(f"hooks naming a relative script absent from the project directory (they may run elsewhere): {len(relative)}")
    unresolved = [h for h in hooks if h["scripts_unresolved"]]
    if unresolved:
        lines.append(f"hooks with a script path this script could not resolve (not checked): {len(unresolved)}")
    if doc["description_overlaps"]:
        top = doc["description_overlaps"][0]
        lines.append(f"description overlaps to review: {len(doc['description_overlaps'])} (highest {top['a']} ~ {top['b']} at {top['jaccard']})")
    if use:
        t = use["tokens_total"]
        cov = use["coverage"]
        lines += [f"last {use['window_days']} days, recognized transcripts under {use['transcript_root']}: {use['sessions']['main']} sessions, "
                  f"{use['sessions']['subagent']} subagent runs, {t.get('requests', 0):,} requests "
                  f"({cov.get('files_read', 0):,} of {cov.get('files_found', 0):,} transcript files read)",
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
                         f"rewrote {rewritten:,} tokens; inferred, not recorded; the largest share is '{top_cause}' ({top['tokens_rewritten']:,})")
        never = doc["never_invoked_in_window"]
        lines.append(f"  never invoked in the window: {len(never['skills'])} of "
                     f"{sum(1 for s in doc['skills'] if s['model_invocable'])} model-invocable skills, "
                     f"{len(never['agents'])} of {len(doc['agents'])} agents")
    if doc["read_scope"]["skipped_outside_scope"] or doc["read_scope"]["confine_external_reads"]:
        lines.append("reads were confined to --home and --project; what that left out is under not_measured in the JSON")
    if doc["unreadable"]:
        lines.append(f"unreadable or unparsed: {len(doc['unreadable'])} (listed in the JSON)")
    return "\n".join(lines)


# ---------------------------------------------------------------- comparing two measurements

def check_baseline_shape(before) -> None:
    """Refuse a baseline that is not a setup measurement of this schema, before anything is measured."""
    if not isinstance(before, dict) or before.get("kind") != "setup":
        raise InputError('the --compare file is not a setup measurement: it has no "kind": "setup" '
                         "(write one with --out; a --piece measurement cannot be compared)")
    if before.get("schema_version") != SCHEMA_VERSION:
        raise InputError(f"the --compare file has schema_version {before.get('schema_version')!r}; this script writes "
                         f"{SCHEMA_VERSION}. Measure again to make a new baseline")

    def damaged(what: str):
        raise InputError(f"the --compare file is damaged: {what}")

    def number(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    for key, kind in (("generated", str), ("home", str), ("project", str), ("fixed_context_est_tokens", dict), ("skills", list),
                      ("agents", list), ("settings", dict), ("description_overlaps", list), ("read_scope", dict),
                      ("user_config", dict), ("usage", dict)):
        if not isinstance(before.get(key), kind):
            damaged(f"`{key}` is missing or has the wrong type")
    if not all(number(v) for v in before["fixed_context_est_tokens"].values()):
        damaged("`fixed_context_est_tokens` holds a value that is not a number")
    if not isinstance(before["settings"].get("hooks"), list):
        damaged("`settings.hooks` is missing or is not a list")
    if not isinstance(before["read_scope"].get("confine_external_reads"), bool):
        damaged("`read_scope.confine_external_reads` is missing or is not true or false")
    if not isinstance(before["user_config"].get("path"), str):
        damaged("`user_config.path` is missing or is not text")
    use = before["usage"]  # {} when the history was not read (--days 0); otherwise every figure compare() reads
    if use:
        sessions, total = use.get("sessions"), use.get("tokens_total")
        never, avg = before.get("never_invoked_in_window"), use.get("avg_prompt_tokens_per_request")
        if not (isinstance(sessions, dict) and number(sessions.get("main"))):
            damaged("`usage.sessions.main` is missing or is not a number")
        if not (isinstance(total, dict) and all(number(v) for v in total.values())):
            damaged("`usage.tokens_total` is missing or holds a value that is not a number")
        if not (isinstance(avg, dict) and all(number(v) for v in avg.values())):
            damaged("`usage.avg_prompt_tokens_per_request` is missing or holds a value that is not a number")
        if not (isinstance(never, dict) and isinstance(never.get("skills"), list) and isinstance(never.get("agents"), list)):
            damaged("`never_invoked_in_window` is missing its skills or agents list")
        for key in ("cache_read_share_of_prompt_tokens", "share_of_spawns_to_agents_defined_here"):
            if use.get(key) is not None and not number(use[key]):
                damaged(f"`usage.{key}` is not a number")


def check_same_setup(before: dict, after: dict) -> None:
    """Refuse two measurements that did not read the same things: a different setup or a different read scope."""
    for key in ("home", "project"):
        if os.path.normcase(str(before.get(key))) != os.path.normcase(str(after.get(key))):
            raise InputError(f"the --compare file measured a different {key} ({before.get(key)}) than this run ({after.get(key)}); "
                             f"compare only measurements of the same setup, with the same --home and --project")
    if before["read_scope"]["confine_external_reads"] != after["read_scope"]["confine_external_reads"]:
        raise InputError("the --compare file and this run have different read scopes (one used --no-external-reads, the other did not); "
                         "the difference in files read would show up as a change in the setup. Measure again with the same setting")
    if os.path.normcase(before["user_config"]["path"]) != os.path.normcase(after["user_config"]["path"]):
        raise InputError(f"the --compare file read a different user-level .claude.json ({before['user_config']['path']}) than this run "
                         f"({after['user_config']['path']}); measure again with the same --user-config")


def compare(before: dict, after: dict) -> str:
    """What changed between two measurements of the same setup. Raises InputError when they cannot be compared."""
    check_baseline_shape(before)
    check_same_setup(before, after)
    try:
        return _compare_lines(before, after)
    except (KeyError, TypeError, AttributeError, ValueError, ArithmeticError) as exc:  # a shape the checks above did not name
        raise InputError(f"the --compare file is damaged: it could not be read as a measurement ({type(exc).__name__}: {exc})") from exc


def _compare_lines(before: dict, after: dict) -> str:
    windows =(as_dict(before.get("usage")).get("window_days"), as_dict(after.get("usage")).get("window_days"))
    same_window = windows[0] == windows[1]

    def pick(doc: dict) -> dict:
        use = doc.get("usage") or {}
        total = use.get("tokens_total", {})
        rows = {f"fixed context: {k} (est. tokens)": v for k, v in doc["fixed_context_est_tokens"].items()}
        rows.update({"skills": len(doc["skills"]), "agents": len(doc["agents"]), "hooks": len(doc["settings"]["hooks"]),
                     "description overlaps to review": len(doc["description_overlaps"])})
        if use and same_window:
            rows.update({
                "main sessions in window": use["sessions"]["main"], "requests in window": total.get("requests", 0),
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
    if not same_window:
        shown = [f"{w} days" if w is not None else "no usage read" for w in windows]
        lines.append(f"  usage rows left out: the windows differ ({shown[0]} before, {shown[1]} after); measure again with the same --days")
    for key in sorted(set(a) | set(b)):
        old, new = a.get(key), b.get(key)
        if old is None or new is None:
            lines.append(f"  {key}: {old} -> {new} (not measured on one side)")
        elif old != new:
            pct = f" ({(new - old) / old:+.1%})" if old else ""
            lines.append(f"  {key}: {old:,} -> {new:,}{pct}")
    if len(lines) == 1 or (len(lines) == 2 and not same_window):
        lines.append("  no measured difference")
    lines.append("usage figures describe each measurement's own window; compare them only when the windows do not overlap")
    return "\n".join(lines)


# ---------------------------------------------------------------- one piece on its own

def piece(path: pathlib.Path, confine: bool = False) -> dict:
    """One skill or subagent file measured on its own, whether or not it is installed anywhere.

    Takes a skill folder (one holding SKILL.md), a SKILL.md file, or a subagent .md file. Anything else
    raises InputError."""
    path = pathlib.Path(path)
    if not path.exists():
        raise InputError(f"no file or folder at {path}")
    scan = Scan([path if path.is_dir() else path.parent], confine)  # the folder named, or the folder of the file named
    if path.is_dir():
        if not (path / "SKILL.md").is_file():
            raise InputError(f"no SKILL.md in {path}: --piece takes a skill folder (one holding SKILL.md), "
                             "a SKILL.md file or a subagent .md file")
        path = path / "SKILL.md"
    is_skill = path.name == "SKILL.md"
    if not is_skill and path.suffix.lower() != ".md":
        raise InputError(f"{path.name} is not a skill or a subagent definition: --piece takes a skill folder, "
                         "a SKILL.md file or a subagent .md file")
    if not scan.allowed(path):  # nothing is opened before this check
        raise InputError(f"{path} is a link to a file outside its own folder, and --no-external-reads is set")
    try:
        path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {type(exc).__name__}") from exc
    record = skill_record(path, "standalone", {}, scan) if is_skill else agent_record(path, "standalone", scan)
    out = {"schema_version": SCHEMA_VERSION, "kind": "piece", "piece_type": "skill" if is_skill else "agent", **record}
    if is_skill:
        # text the skill can send its reader to, totalled per folder; none of it loads until it is read
        folders = collections.defaultdict(lambda: {"files": 0, "est_tokens": 0})
        for p in path.parent.rglob("*"):
            if p.parent != path.parent and ".git" not in p.parts and p.suffix in (".md", ".txt") and scan.is_file(p):
                entry = folders[p.relative_to(path.parent).parts[0]]
                entry["files"] += 1
                entry["est_tokens"] += est_tokens(len(scan.read(p)))
        out["bundled"] = dict(sorted(folders.items()))
    out.update({
        "estimate_note": f"est_tokens = characters / {CHARS_PER_TOKEN}; an estimate, not a tokenizer count",
        "policy": POLICY,
        "read_scope": {"confine_external_reads": confine, "skipped_outside_scope": sorted(set(scan.skipped_outside))[:SKIPPED_SHOWN]},
        "not_measured": [
            f"the listing cost uses the documented cap ({LISTING_CAP} characters); skillListingMaxDescChars and skillOverrides of the setup it will live in are not applied",
            "usage: the session history is not read in this mode",
            "files in `bundled` other than .md and .txt, and files directly in the skill folder",
            "frontmatter is read by a line-based reader that covers a subset of YAML (see parse_notes)"],
        "unreadable": scan.unreadable})
    return out


# ---------------------------------------------------------------- command line

def _block(title: str) -> str:
    """A titled, indented block of the module docstring, so --help and the docstring cannot drift apart."""
    m = re.search(r"^%s:\n((?:[ ]+.*\n|\n(?=[ ]))*)" % re.escape(title), __doc__ or "", re.M)
    return f"{title}:\n{m.group(1)}" if m else ""


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="measure.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(__doc__ or "").split("\n\n")[0] + "\n\nIt counts and lists; it does not judge. Local files only, no network.",
        epilog="\n".join([_block("Modes and combinations"), _block("Exit codes"),
                          "Full description, output keys and the list of what is read: see the docstring at the top of this file."]))
    ap.add_argument("--home", default=None, metavar="DIR",
                    help="user-level Claude Code directory (default: $CLAUDE_CONFIG_DIR, else ~/.claude)")
    ap.add_argument("--project", default=None, metavar="DIR", help="project directory (default: the current directory)")
    ap.add_argument("--days", type=int, default=None, metavar="N",
                    help=f"days of session history to read; 0 skips it (default: {DEFAULT_DAYS}, at most {MAX_DAYS})")
    ap.add_argument("--out", default=None, metavar="FILE",
                    help="also write the full JSON here, readable by the current user only where the system allows; "
                         "the directory must exist; must differ from --compare")
    ap.add_argument("--compare", default=None, metavar="FILE",
                    help="a setup JSON written earlier with --out; also prints what changed since (same --home and --project)")
    ap.add_argument("--piece", default=None, metavar="PATH",
                    help="measure one skill folder, SKILL.md or subagent .md file on its own, and stop; "
                         "takes only --out and --no-external-reads")
    ap.add_argument("--user-config", default=None, metavar="FILE",
                    help="the user-level .claude.json (default: inside --home when it is $CLAUDE_CONFIG_DIR, "
                         "beside --home when that is named .claude, else inside --home)")
    ap.add_argument("--no-external-reads", action="store_true",
                    help="read nothing outside --home and --project: no ancestor directories, no imports or symlink "
                         "targets elsewhere (for reviewing someone else's setup)")
    return ap


def write_private(path: pathlib.Path, text: str) -> None:
    """Write the report readable by the current user only where the system has modes (on Windows the folder's ACL applies)."""
    # No O_TRUNC: a file that already exists keeps its old mode, so restrict it first and only then empty it.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        if HAS_MODES:
            os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.write(text)


def same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        if a.exists() and b.exists():
            return os.path.samefile(a, b)
    except OSError:
        pass
    return same_path(a, b)


def check_out(args) -> pathlib.Path | None:
    if args.out is None:
        return None
    if not args.out.strip():
        raise InputError("--out needs a file name")
    out = pathlib.Path(args.out).expanduser()
    if out.is_dir():
        raise InputError(f"--out names a folder, not a file: {out}")
    if not out.parent.is_dir():
        raise InputError(f"the folder for --out does not exist: {out.parent}")
    return out


def run(args) -> int:
    out = check_out(args)
    if args.piece is not None:
        clash = [flag for flag, value in (("--home", args.home), ("--project", args.project), ("--days", args.days),
                                           ("--user-config", args.user_config), ("--compare", args.compare)) if value is not None]
        if clash:
            raise InputError(f"--piece measures one file on its own; {', '.join(clash)} describe a setup and cannot be combined with it")
        text = json.dumps(piece(pathlib.Path(args.piece).expanduser(), args.no_external_reads), indent=2, ensure_ascii=False)
        print(text)
        return write_report(out, text + "\n")
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR") or None
    try:
        home = pathlib.Path(args.home or env_dir or pathlib.Path.home() / ".claude").expanduser()
    except RuntimeError as exc:
        raise InputError("cannot tell the home directory; pass --home <dir>") from exc
    if not home.is_dir():
        raise InputError(f"no Claude Code directory at {home}; pass --home <dir> (default: $CLAUDE_CONFIG_DIR, else ~/.claude)")
    project = pathlib.Path(args.project or ".").expanduser().resolve()
    if not project.is_dir():
        raise InputError(f"no project directory at {project}; pass --project <dir>")
    days = DEFAULT_DAYS if args.days is None else args.days
    if not 0 <= days <= MAX_DAYS:
        raise InputError(f"--days must be between 0 and {MAX_DAYS}, not {days}")
    if args.user_config is not None and not pathlib.Path(args.user_config).expanduser().is_file():
        raise InputError(f"--user-config: no file at {args.user_config}")
    baseline = None
    if args.compare is not None:
        cmp_path = pathlib.Path(args.compare).expanduser()
        if not cmp_path.is_file():
            raise InputError(f"--compare: no file at {cmp_path}")
        if out is not None and same_file(out, cmp_path):
            raise InputError(f"--out and --compare name the same file ({cmp_path}); --out would replace the baseline "
                             "before it is compared. Write the new measurement to a different file")
        try:
            baseline = json.loads(cmp_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError) as exc:
            raise InputError(f"--compare: {cmp_path} is not readable JSON ({type(exc).__name__})") from exc
        check_baseline_shape(baseline)
    config = resolve_user_config(home, args.user_config, env_dir)
    doc = build(home, project, days, confine=args.no_external_reads, user_config=config,
                user_home=resolve_user_home(home, env_dir))
    changes = compare(baseline, doc) if baseline is not None else None  # every refusal comes before anything is written
    status = write_report(out, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(summary(doc))
    if changes is not None:
        print("\n" + changes)
    return status


def write_report(out, text: str) -> int:
    if out is None:
        return 0
    try:
        write_private(out, text)
    except OSError as exc:
        print(f"measure.py: could not write {out}: {type(exc).__name__}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        return run(args)
    except InputError as exc:
        print(f"measure.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
