#!/usr/bin/env python3
"""Deterministic oracle for the `planted` fixture after an upgrade: which of its ten defects are gone.

Usage: check_upgrade.py <fixture root>
<fixture root> is the `planted` folder that build_fixtures.py wrote (it holds `home/.claude` and `project`), or
the output folder that holds `planted/`. Run it after an upgrade has edited that copy; run it on a fresh build
and every defect must read "not fixed" (the null baseline).

Prints one line per check, in this order:
  D1..D10   `D<n> fixed: <why>` or `D<n> not fixed: <why>`, one per defect in ANSWER-KEY.md. A fix is judged by
            what the setup does where it can be run (D1, D2: the guard script is run with a sample PreToolUse
            payloads: pushes to main in three forms, MUST_BLOCK, must be blocked, and branches that only
            contain the word, MUST_PASS, must not) and by structure elsewhere (D3 to D10). Any reasonable fix passes, not one wording; where
            a defect allows removal (an agent, a skill, a hook entry) removal passes.
  S1..S5    `S<n> kept: <why>` or `S<n> lost: <why>`: what the key lists as sound must survive (the integer-cents
            rule and its reason, the test command, the renamer's prompt, the deploy-staging commands) and every file
            that no defect touches (the session transcripts, compared by hash with a fresh build, their
            build-time timestamps aside) is unchanged.
and a last line with the two counts.

The fixture is never modified: every check runs on a temporary copy. The guard scripts the setup wires are
executed (python, or bash for .sh) in that copy with a 10-second limit, as Claude Code would run them, so
point this at a fixture you built, not at a setup you do not trust.

Exit codes:
  0  every defect fixed and every survival check kept
  1  anything else: a defect not fixed, something sound lost, or a check that could not run (counted as failed)
  2  usage: not exactly one argument, a flag, or a folder that is not a `planted` fixture (this text goes to stderr)

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_fixtures  # noqa: E402  (the same builder that wrote the fixture, for the fresh copy S5 compares with)

RUN_LIMIT = 10  # seconds a guard script may run
SCRIPT_EXT = r"(?:py|sh)"
AGENT_KEYS = {"name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns", "skills", "mcpServers",
              "hooks", "memory", "background", "effort", "isolation", "color", "initialPrompt"}
MODEL_ALIASES = {"haiku", "sonnet", "opus", "inherit"}
MODEL_ID = re.compile(r"claude-[\w.-]+(?:\[1m\])?")
PUSH_MAIN = "git push origin main"
PUSH_OTHER = "git push origin domain-fix"  # contains "main" as a substring: a guard that matches text blocks it by mistake
# A guard must block every push to main a reviewer would try, and let through branches that only contain the word.
MUST_BLOCK = (PUSH_MAIN, "git push origin HEAD:main", "git -C . push origin main")
MUST_PASS = (PUSH_OTHER, "git push origin feature-main")
# What the planted files are, relative to the fixture root. Files no defect touches are everything else.
DEFECT_FILES = {
    "project/CLAUDE.md", "home/.claude/hooks/guard_main.py", "home/.claude/settings.json",
    "home/.claude/agents/helper.md", "home/.claude/agents/renamer.md",
    "home/.claude/skills/deploy-staging/SKILL.md", "home/.claude/skills/release-staging/SKILL.md",
    "home/.claude/skills/audit-readonly/SKILL.md", "home/.claude/skills/repo-stats/SKILL.md"}
MONTH_END = ("make export-ledger", "reconcile.py", "make lock-month", "close-<yyyy-mm>", "PERIOD_OPEN", "exports/archive")


# ---------------------------------------------------------------- reading the fixture

def frontmatter(text: str):
    """({key: value}, body). Indented lines continue the key above; a file without frontmatter has none."""
    m = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", text, re.S)
    if not m:
        return {}, text
    fields, key = {}, None
    for line in m.group(1).splitlines():
        top = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if top and not line[0].isspace():
            key = top.group(1)
            fields[key] = top.group(2).strip().strip("\"'")
        elif key and line.strip():
            fields[key] = (fields[key] + " " + line.strip().lstrip("- ").strip()).strip()
    return fields, m.group(2)


class Setup:
    """The copy under test: files, settings, hooks, and the commands run against it."""

    def __init__(self, root: pathlib.Path, original: pathlib.Path):
        self.root, self.original = root, original
        self.home, self.project = root / "home" / ".claude", root / "project"
        self.invalid_settings: list = []
        self.settings: list = []  # (label, dict)
        for label, path in (("user settings.json", self.home / "settings.json"),
                            ("project settings.json", self.project / ".claude" / "settings.json"),
                            ("project settings.local.json", self.project / ".claude" / "settings.local.json")):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("not an object")
            except (OSError, ValueError):
                self.invalid_settings.append(label)
                continue
            self.settings.append((label, data))

    def text(self, path: pathlib.Path) -> str:
        try:
            return path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return ""

    def hooks(self):
        """(settings label, event, matcher, command) for every command hook in the settings files."""
        found = []
        for label, data in self.settings:
            hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
            for event, groups in hooks.items():
                for group in groups if isinstance(groups, list) else []:
                    group = group if isinstance(group, dict) else {}
                    for hook in group.get("hooks") if isinstance(group.get("hooks"), list) else []:
                        if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                            found.append((label, str(event), str(group.get("matcher", "")), hook["command"]))
        return found

    def deny_rules(self) -> list:
        rules = []
        for _, data in self.settings:
            deny = data.get("permissions", {}).get("deny") if isinstance(data.get("permissions"), dict) else None
            rules += [r for r in deny if isinstance(r, str)] if isinstance(deny, list) else []
        return rules

    def settings_model(self) -> str:
        model = ""
        for _, data in self.settings:  # the later file wins
            if isinstance(data.get("model"), str):
                model = data["model"]
        return model

    def scripts_in(self, command: str) -> list:
        """(word as written, resolved path or None when a variable is unknown) for each script file the command names."""
        try:
            words = shlex.split(command.replace("\\", "/"))
        except ValueError:
            words = command.replace("\\", "/").split()
        out = []
        for word in words:
            if not re.search(r"\." + SCRIPT_EXT + r"$", word, re.I):
                continue
            token = word
            for var in ("HOME", "USERPROFILE"):
                token = re.sub(r"\$\{%s\}|\$%s(?![A-Za-z0-9_])|%%%s%%" % (var, var, var), (self.root / "home").as_posix(), token)
            token = re.sub(r"\$\{CLAUDE_PROJECT_DIR\}|\$CLAUDE_PROJECT_DIR(?![A-Za-z0-9_])|%CLAUDE_PROJECT_DIR%", self.project.as_posix(), token)
            if token == "~" or token.startswith("~/"):
                token = (self.root / "home" / token[2:]).as_posix()
            if re.search(r"[$%`*?{]", token) or token.startswith("~"):
                out.append((word, None))
                continue
            path = pathlib.Path(token)
            if not path.is_absolute():
                path = self.project / token
            else:  # an absolute path into the fixture as it was built points at the copy
                try:
                    path = self.root / path.relative_to(self.original)
                except ValueError:
                    pass
            out.append((word, path))
        return out


def covers_bash(matcher: str) -> bool:
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, "Bash") is not None
    except re.error:
        return "Bash" in matcher


def run_guard(setup: Setup, command: str, argv_script: pathlib.Path, rest: list, shell_text: str) -> dict:
    """Run a PreToolUse command script with a sample Bash payload. {blocked, rc, note}."""
    payload = json.dumps({"session_id": "check-upgrade", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": shell_text}, "cwd": str(setup.project)})
    if argv_script.suffix.lower() == ".py":
        argv = [sys.executable, str(argv_script), *rest]
    else:
        bash = shutil.which("bash")
        if not bash:
            return {"blocked": False, "rc": None, "note": f"{argv_script.name} needs bash, which is not available here"}
        argv = [bash, str(argv_script), *rest]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(setup.project), "HOME": str(setup.root / "home")}
    try:
        done = subprocess.run(argv, input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=RUN_LIMIT, cwd=str(setup.project), env=env)
    except subprocess.TimeoutExpired:
        return {"blocked": False, "rc": None, "note": f"{argv_script.name} did not finish in {RUN_LIMIT} seconds"}
    except OSError as exc:
        return {"blocked": False, "rc": None, "note": f"{argv_script.name} could not run ({type(exc).__name__})"}
    blocked = done.returncode == 2
    if done.returncode == 0:  # the documented JSON form of a block, on exit 0
        try:
            reply = json.loads(done.stdout)
            decision = (reply.get("hookSpecificOutput") or {}).get("permissionDecision") or reply.get("decision")
            blocked = decision in ("deny", "block")
        except (ValueError, AttributeError):
            pass
    return {"blocked": blocked, "rc": done.returncode, "note": ""}


def all_of(results) -> dict:
    """Blocked only if every command was blocked; otherwise the first that got through."""
    results = list(results)
    miss = next((r for r in results if not r["blocked"]), None)
    return {"blocked": True, "rc": results[0]["rc"], "note": ""} if miss is None else         {"blocked": False, "rc": miss["rc"], "note": miss["note"] or f"exits {miss['rc']} on `{miss['cmd']}`, which is not blocked"}


def any_of(results) -> dict:
    """Blocked if any command was blocked (for commands that must pass)."""
    results = list(results)
    hit = next((r for r in results if r["blocked"]), None)
    return {"blocked": False, "rc": results[0]["rc"], "note": ""} if hit is None else {"blocked": True, "rc": hit["rc"], "note": f"blocks `{hit['cmd']}`"}


def guards(setup: Setup) -> list:
    """Each PreToolUse hook that covers Bash and names a script, exercised on a push to main and a push to domain-fix."""
    found = []
    for label, event, matcher, command in setup.hooks():
        if event != "PreToolUse" or not covers_bash(matcher):
            continue
        scripts = setup.scripts_in(command)
        runnable = next(((w, p) for w, p in scripts if p is not None and p.is_file()), None)
        if runnable is None:
            found.append({"command": command, "script": None, "note": "names no script file that exists, so it cannot be exercised"})
            continue
        word, path = runnable
        words = command.replace("\\", "/").split()
        rest = words[words.index(word) + 1:] if word in words else []
        main = all_of(run_guard(setup, command, path, rest, c) | {"cmd": c} for c in MUST_BLOCK)
        other = any_of(run_guard(setup, command, path, rest, c) | {"cmd": c} for c in MUST_PASS)
        found.append({"command": command, "script": path, "main": main, "other": other, "note": ""})
    return found


def push_deny(rule: str) -> bool:
    m = re.fullmatch(r"\s*Bash\((.*)\)\s*", rule)
    inner = m.group(1) if m else ""
    return "git push" in inner and ("main" in inner or inner.rstrip().endswith(("*", ":*")))


# ---------------------------------------------------------------- the checks

class Checks:
    def __init__(self, setup: Setup, fresh: pathlib.Path):
        self.s, self.fresh = setup, fresh
        self.guard_list = guards(setup)
        self.denies = [r for r in setup.deny_rules() if push_deny(r)]
        self.good = [g for g in self.guard_list if g.get("main") and g["main"]["blocked"] and not g["other"]["blocked"]]

    def agent(self, name: str):
        path = self.s.home / "agents" / f"{name}.md"
        return (frontmatter(self.s.text(path)) if path.is_file() else None), path

    def skill(self, name: str):
        path = self.s.home / "skills" / name / "SKILL.md"
        return (frontmatter(self.s.text(path)) if path.is_file() else None), path

    def guard_detail(self) -> str:
        if not self.guard_list:
            return "no PreToolUse hook covers Bash and no deny rule names a push to main"
        parts = []
        for g in self.guard_list:
            if not g["script"]:
                parts.append(g["note"])
            elif not g["main"]["blocked"]:
                why = g["main"]["note"] or f"exits {g['main']['rc']} on `{PUSH_MAIN}` (only exit 2 blocks)"
                parts.append(f"{g['script'].name} {why}")
            else:
                parts.append(f"{g['script'].name} also {g['other']['note']}")
        return "; ".join(parts)

    def d1(self):
        if self.good:
            return True, f"enforced outside prose: {self.good[0]['script'].name} blocks `{PUSH_MAIN}` and lets `{PUSH_OTHER}` through"
        if self.denies:
            return True, f"enforced outside prose: deny rule {self.denies[0]}"
        return False, "the never-push-to-main rule is enforced only in prose: " + self.guard_detail()

    def d2(self):
        if self.good:
            return True, f"{self.good[0]['script'].name} blocks `{PUSH_MAIN}` (exit {self.good[0]['main']['rc']}) and lets `{PUSH_OTHER}` through"
        if not self.guard_list and self.denies:
            return True, "the exit-1 guard is no longer wired; a deny rule enforces the rule instead"
        return False, self.guard_detail()

    def d3(self):
        found, path = self.agent("helper")
        if found is None:
            return True, "helper.md was removed"
        fields, _ = found
        typos = [k for k in fields if k not in AGENT_KEYS and difflib.get_close_matches(k, AGENT_KEYS, n=1, cutoff=0.7)]
        model = fields.get("model", "")
        known = model.lower() in MODEL_ALIASES or MODEL_ID.fullmatch(model) is not None
        if typos:
            return False, f"helper.md still has the unrecognised field `{typos[0]}`, which Claude Code ignores"
        if not known:
            return False, f"helper.md has {'model ' + repr(model) if model else 'no model'}: not a recognised model"
        return True, f"helper.md has no misspelled field and model: {model}"

    def d4(self):
        found, _ = self.agent("helper")
        if found is None:
            return True, "helper.md was removed"
        fields, body = found
        words = lambda text: len(re.findall(r"\w+", text))  # noqa: E731
        missing = []
        if words(fields.get("description", "")) < 8:
            missing.append("a description of eight words or more that says when to use it")
        if words(body) < 40:
            missing.append("a prompt of forty words or more about the job and its limits")
        if not re.search(r"\b(return|report|respond|output|summar\w+|answer)", body, re.I):
            missing.append("what the agent returns")
        if not fields.get("tools"):
            missing.append("a tools list (none means every tool)")
        return (not missing, "helper.md now has description, prompt, return and tools" if not missing
                else "helper.md still lacks " + "; ".join(missing))

    def d5(self):
        (dep, _), (rel, _) = self.skill("deploy-staging"), self.skill("release-staging")
        if dep is None or rel is None:
            return True, f"{'deploy-staging' if dep is None else 'release-staging'} was removed: one skill answers the request"
        for name, (fields, _) in (("deploy-staging", dep), ("release-staging", rel)):
            if fields.get("disable-model-invocation", "").lower() == "true":
                return True, f"{name} is no longer offered to the model (disable-model-invocation), so the descriptions no longer compete"
        for name, other, (fields, _) in (("deploy-staging", "release-staging", dep), ("release-staging", "deploy-staging", rel)):
            if other in fields.get("description", ""):
                return True, f"{name}'s description names {other}, so the model can tell them apart"
        return False, "both descriptions still claim deploy, release and ship to staging, and neither names the other"

    def importing(self, path: pathlib.Path, seen=None, depth=0) -> str:
        """The text of a file and of the files it imports with @path (what loads with it), to four hops."""
        seen = seen if seen is not None else set()
        if path in seen or depth > 4 or not path.is_file():
            return ""
        seen.add(path)
        text = self.s.text(path)
        for ref in re.findall(r"(?<![\w`@/])@([\w./~-]+)", text):
            target = (self.s.root / "home" / ref[2:]) if ref.startswith("~/") else path.parent / ref
            text += "\n" + self.importing(target, seen, depth + 1)
        return text

    def d6(self):
        text = self.importing(self.s.project / "CLAUDE.md")
        present = [m for m in MONTH_END if m.lower() in text.lower()]
        if len(present) > 2:
            return False, f"CLAUDE.md still carries the month-end procedure ({len(present)} of its {len(MONTH_END)} commands)"
        moved = next((str(p.relative_to(self.s.root)).replace("\\", "/") for p in self.s.root.rglob("*")
                      if p.is_file() and p.suffix in (".md", ".sh", ".py") and p.name != "CLAUDE.md"
                      and sum(m.lower() in self.s.text(p).lower() for m in MONTH_END) >= 4), None)
        return True, "the month-end steps are out of CLAUDE.md" + (f" and now live in {moved}" if moved else " (removed, not moved: no file holds them)")

    def d7(self):
        found, _ = self.skill("audit-readonly")
        if found is None:
            return True, "audit-readonly was removed"
        body = re.sub(r"\s+", " ", found[1].replace("`", ""))
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            low = sentence.lower()
            disclaims = re.search(r"pre-?approv|(does not|doesn't|do not|not) (restrict|limit|prevent|make|mean)|not a (restriction|sandbox)|no restriction|without restrict", low)
            claims = (re.search(r"(?<!dis)allowed-tools", low) and re.search(r"cannot|can't|unable|only|restrict|limit|prevent|safe|read-only|guarantee|enforce", low)) \
                or re.search(r"\b(cannot|can't|can not|unable to) (modify|write|edit|run|change)", low)
            if claims and not disclaims:
                return False, f"the body still says allowed-tools makes the skill safe or read-only: \"{sentence[:90]}\""
        return True, "the body no longer claims allowed-tools restricts the skill"

    def d8(self):
        found, path = self.skill("repo-stats")
        if found is None:
            return True, "repo-stats was removed"
        body = found[1]
        manual = re.search(r"(open|read) every (source )?file|by reading (it|each|every)|in your head|one at a time|running total", body, re.I)
        scripted = re.search(r"`[^`\n]+`|```", body) or any(p != path for p in path.parent.rglob("*") if p.is_file())
        if manual:
            return False, f"the body still has the model count lines by reading files (\"{manual.group(0)}\")"
        if not scripted:
            return False, "the reading-and-counting is gone but the body names no command or script to count with"
        return True, "the body counts with a command or script, not by reading every file"

    def d9(self):
        if self.s.invalid_settings:
            return False, f"{', '.join(self.s.invalid_settings)} is not valid JSON: its hooks cannot be judged"
        for label, event, _, command in self.s.hooks():
            for word, path in self.s.scripts_in(command):
                if path is not None and not path.exists():
                    return False, f"a {event} hook in {label} runs {word}, which does not exist"
        return True, "every hook script exists, or the entry is gone"

    def d10(self):
        found, _ = self.agent("renamer")
        if found is None:
            return True, "renamer.md was removed"
        fields, _ = found
        model = fields.get("model") or self.s.settings_model()
        effort = fields.get("effort", "")
        top_tier = "opus" in model.lower()  # an alias or an id such as claude-opus-5-5
        if top_tier and effort.lower() not in ("low", "medium"):
            return False, (f"renamer still runs on {model} at effort {effort or '(unset)'} for mechanical renaming: "
                           "off the top tier, or at low or medium effort, is needed")
        return True, f"renamer runs on {fields.get('model') or 'the session model'} at effort {effort or '(unset)'}"

    # survival

    def s1(self):
        text = self.s.text(self.s.project / "CLAUDE.md").lower()
        ok = "integer cents" in text and "decimal" in text and "rounding" in text
        return ok, "CLAUDE.md keeps the integer-cents rule and its reason" if ok else "CLAUDE.md lost the integer-cents rule or the rounding-bugs reason"

    def s2(self):
        text = self.s.text(self.s.project / "CLAUDE.md")
        ok = "make test" in text and "docker compose up db" in text
        return ok, "CLAUDE.md keeps the test command and the database it needs" if ok else "CLAUDE.md lost `make test` or `docker compose up db`"

    def s3(self):
        found, _ = self.agent("renamer")
        body = found[1] if found else ""
        ok = all(p in body for p in ("Find every occurrence with Grep", "report what is left", "Return the count changed"))
        return ok, "the renamer prompt (job, method, return) is intact" if ok else "the renamer prompt lost its method or its return"

    def s4(self):
        text = "\n".join(self.s.text(p) for p in (self.s.home / "skills").rglob("SKILL.md")) if (self.s.home / "skills").is_dir() else ""
        ok = all(c in text for c in ("make image", "make push ENV=staging", "make smoke ENV=staging"))
        return ok, "the deploy-staging commands are still in a skill" if ok else "the deploy-staging commands (make image, push, smoke) are gone from every skill"

    def s5(self):
        def digest(path: pathlib.Path) -> str:
            data = path.read_bytes()
            if path.suffix == ".jsonl":  # the build stamps rows with its own time
                data = re.sub(rb"\d{4}-\d\d-\d\dT[\d:.]+Z", b"T", data)
            return hashlib.sha256(data).hexdigest()

        changed = []
        for path in sorted(p for p in self.fresh.rglob("*") if p.is_file()):
            rel = path.relative_to(self.fresh).as_posix()
            if rel in DEFECT_FILES:
                continue
            mine = self.s.root / rel
            if not mine.is_file() or digest(mine) != digest(path):
                changed.append(rel)
        return (not changed, "every file no defect touches is unchanged" if not changed
                else "changed or removed: " + ", ".join(changed))


def check(root: pathlib.Path):
    """[(label, passed, why)] for D1..D10 and S1..S5 on the fixture at root."""
    with tempfile.TemporaryDirectory() as tmp:
        work, fresh = pathlib.Path(tmp) / "copy", pathlib.Path(tmp) / "fresh"
        shutil.copytree(root, work, symlinks=True)
        build_fixtures.planted(fresh)
        checks = Checks(Setup(work, root.resolve()), fresh)
        rows = []
        for label in [f"D{i}" for i in range(1, 11)] + [f"S{i}" for i in range(1, 6)]:
            try:
                passed, why = getattr(checks, label.lower())()
            except Exception as exc:  # a check that cannot run counts as failed, and says so
                passed, why = False, f"the check could not run ({type(exc).__name__}: {exc})"
            rows.append((label, bool(passed), why))
    return rows


def find_root(arg: str):
    root = pathlib.Path(arg).expanduser().resolve()
    for candidate in (root, root / "planted"):
        if (candidate / "home" / ".claude").is_dir() and (candidate / "project").is_dir():
            return candidate
    return None


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    root = find_root(argv[0])
    if root is None:
        print(f"check_upgrade.py: {argv[0]} is not a planted fixture: expected home/.claude and project in it "
              "(or in its planted/ folder)", file=sys.stderr)
        return 2
    rows = check(root)
    for label, passed, why in rows:
        word = ("fixed" if passed else "not fixed") if label.startswith("D") else ("kept" if passed else "lost")
        print(f"{label} {word}: {why}")
    fixed = sum(1 for label, ok, _ in rows if label.startswith("D") and ok)
    kept = sum(1 for label, ok, _ in rows if label.startswith("S") and ok)
    print(f"defects fixed: {fixed} of 10; sound things kept: {kept} of 5")
    return 0 if fixed == 10 and kept == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
