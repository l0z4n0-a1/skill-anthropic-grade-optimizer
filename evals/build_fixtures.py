#!/usr/bin/env python3
"""Build two throwaway Claude Code setups for calibrating the review.

`planted/` has ten defects, each documented in ANSWER-KEY.md with the knowledge-base
claims that make it a defect. `clean/` is a small setup with nothing wrong that
matters. Running the skill against both answers the two questions that decide
whether a reviewer can be trusted: how many real defects does it find, and how
many does it invent?

Usage: build_fixtures.py <output dir>
Writes <output dir>/planted and <output dir>/clean, each with `home/.claude` and
`project`. Session history is generated with current timestamps so it falls
inside the measurement window, so the transcripts carry the time of the build (the other
files do not depend on it). Nothing here is executed by the review.
Use a new, empty output directory: the named folders are overwritten file by file, and a
file left from an earlier build that this one does not write stays in place. A failed
write raises and exits 1 with a traceback.
Exit: 0 when both folders were built; 2 when the arguments are not exactly one directory
(a flag such as --help also gives 2 and prints this text to stderr).
"""
import datetime as dt
import json
import pathlib
import sys


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def session(path: pathlib.Path, model: str, skills: dict, agents: dict, requests: int, prompt_tokens: int) -> None:
    """A synthetic transcript: counts and token totals only, shaped like Claude Code's."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows, n = [], 0
    calls = [("Skill", {"skill": s}) for s, k in skills.items() for _ in range(k)]
    calls += [("Agent", ({"subagent_type": a} if a else {}) | {"prompt": "task"}) for a, k in agents.items() for _ in range(k)]
    for i in range(requests):
        content = []
        if calls:
            name, args = calls.pop()
            n += 1
            content.append({"type": "tool_use", "id": f"{path.stem}-t{n}", "name": name, "input": args})
        rows.append({"type": "assistant", "timestamp": now, "effort": "medium", "message": {
            "id": f"{path.stem}-m{i}", "model": model, "content": content,
            "usage": {"input_tokens": 20, "cache_creation_input_tokens": 2000,
                      "cache_read_input_tokens": prompt_tokens, "output_tokens": 600}}})
    write(path, "\n".join(json.dumps(r) for r in rows) + "\n")


def planted(base: pathlib.Path) -> None:
    home, project = base / "home" / ".claude", base / "project"

    # D1 a guarantee written as prose, shouted and repeated. D6 a monthly procedure in the always-loaded file.
    write(project / "CLAUDE.md", """# Billing service

Python 3.12 service that issues invoices. Tests run with `make test`; the suite
needs the local Postgres from `docker compose up db`.

IMPORTANT: NEVER push directly to main. ALWAYS open a pull request.

Money is stored as integer cents everywhere. The `Decimal` type appears only at
the API boundary, because two rounding bugs came from mixing the two.

## Month-end close procedure

Run this on the first business day of each month.

1. Export the ledger: `make export-ledger MONTH=<yyyy-mm>`.
2. Open `exports/ledger-<yyyy-mm>.csv` and check the row count against the
   count printed by the export.
3. Run `python tools/reconcile.py exports/ledger-<yyyy-mm>.csv`.
4. For each mismatch the script prints, open the invoice in the admin panel and
   compare line totals with the ledger row.
5. Record each resolved mismatch in `docs/close-log.md` with the invoice id.
6. When the script prints zero mismatches, run `make lock-month MONTH=<yyyy-mm>`.
7. Email the summary the lock command prints to finance.
8. Tag the commit `close-<yyyy-mm>`.
9. If the lock command fails with `PERIOD_OPEN`, a late invoice was issued:
   rerun from step 1.
10. Archive the export under `exports/archive/`.

CRITICAL: REMEMBER, NEVER PUSH TO MAIN!!! This is the MOST IMPORTANT rule.
""")

    # D2 the hook exits 1, which reports an error but does not block. D9 a second hook names a script that is absent.
    write(home / "hooks" / "guard_main.py", """#!/usr/bin/env python3
\"\"\"Blocks `git push` to main. Reads the tool call from stdin.\"\"\"
import json
import sys

call = json.load(sys.stdin)
command = call.get("tool_input", {}).get("command", "")
if "git push" in command and "main" in command:
    print("Pushing to main is not allowed.", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
""")
    write(home / "settings.json", json.dumps({
        "model": "opus",
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python ~/.claude/hooks/guard_main.py", "timeout": 5}]}],
            "PostToolUse": [{"matcher": "Edit|Write", "hooks": [
                {"type": "command", "command": "python ~/.claude/hooks/format_changed.py", "timeout": 30}]}]},
    }, indent=2))

    # D3 a misspelled field: `modle` is ignored, so the agent runs on the session's model.
    # D4 a description that cannot win a request, every tool, and a prompt that says nothing about the job or the return.
    write(home / "agents" / "helper.md", """---
name: helper
description: Helps with code.
modle: haiku
---
You are a helpful assistant. Do what is asked carefully and thoroughly.
""")
    # D10 mechanical work pinned to the most capable tier at the highest effort.
    write(home / "agents" / "renamer.md", """---
name: renamer
description: Renames files and symbols across the repository to a given naming rule, and updates every import that refers to them. Use when a rename touches more than a handful of files.
model: opus
effort: max
tools: Read, Edit, Grep, Glob, Bash
---
You apply one naming rule across the repository. The delegation message gives
the rule and the scope.

Find every occurrence with Grep before changing anything, so the count is known.
Change files in place. After the last change, search again for the old name and
report what is left: a remaining occurrence is either an exception to the rule
or a miss, and the main session needs to know which.

Return the count changed, the files touched, and any occurrence you left alone
with the reason.
""")

    # D5 two skills that claim the same request, neither naming the other.
    write(home / "skills" / "deploy-staging" / "SKILL.md", """---
name: deploy-staging
description: Deploys the current branch to the staging environment and runs the smoke tests. Use when asked to deploy, ship or release to staging.
---
Build the image with `make image`, push it with `make push ENV=staging`, then
run `make smoke ENV=staging`. A smoke failure means the deploy is not done: read
the failing check's log and report it.
""")
    write(home / "skills" / "release-staging" / "SKILL.md", """---
name: release-staging
description: Releases the current branch to staging and verifies it with smoke tests. Use when asked to release, deploy or ship to the staging environment.
---
Run `scripts/release.sh staging`. It builds, pushes and runs the smoke tests.
If it exits non-zero, report the last twenty lines of its output.
""")

    # D7 the author believes allowed-tools restricts the skill; it only pre-approves.
    write(home / "skills" / "audit-readonly" / "SKILL.md", """---
name: audit-readonly
description: Read-only audit of the repository's dependency licences. Use when asked which licences the dependencies carry or whether a dependency is safe to ship.
allowed-tools: Read, Grep, Glob
---
This skill is read-only: because of `allowed-tools`, it cannot modify files or
run commands, so it is safe to use on a production checkout.

List each dependency from the lock file with its declared licence. Flag any
licence that is not MIT, BSD or Apache-2.0, and say where the declaration was
found.
""")

    # D8 a deterministic chore handed to the model.
    write(home / "skills" / "repo-stats" / "SKILL.md", """---
name: repo-stats
description: Reports the size of the codebase by language. Use when asked how big the repository is or how the code splits across languages.
---
Open every source file in the repository one at a time. For each file, count its
lines by reading it, and add the count to a running total for the file's
language. Keep the totals in your head as you go. When every file has been read,
present the totals as a table.
""")

    # Usage: `release-staging` never runs; unspecified spawns dominate; `helper` is never chosen.
    session(home / "projects" / "billing" / "s1.jsonl", "claude-opus-5-5",
            {"deploy-staging": 6, "repo-stats": 3}, {"": 14, "renamer": 4}, requests=60, prompt_tokens=90000)
    session(home / "projects" / "billing" / "s2.jsonl", "claude-opus-5-5",
            {"deploy-staging": 2, "audit-readonly": 1}, {"": 9, "renamer": 2}, requests=40, prompt_tokens=70000)


def clean(base: pathlib.Path) -> None:
    home, project = base / "home" / ".claude", base / "project"
    write(project / "CLAUDE.md", """# Billing service

Python 3.12 service that issues invoices. Tests run with `make test`; the suite
needs the local Postgres from `docker compose up db`.

Run one test file with `make test ARGS=tests/test_invoice.py`. A change is done
when the tests that cover it pass; say which ones you ran.

Money is stored as integer cents everywhere. The `Decimal` type appears only at
the API boundary, because two rounding bugs came from mixing the two.

Tests for a module live beside it as `test_<module>.py`, so a reader finds them
without searching.
""")
    write(home / "hooks" / "format_changed.py", """#!/usr/bin/env python3
\"\"\"Formats the file an edit just touched.

In:   the PostToolUse payload on stdin.
Out:  always exit 0; formatting is a convenience and must never stop work.
Fail: an unreadable payload or a missing formatter is ignored.
\"\"\"
import json
import subprocess
import sys

try:
    path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    if path.endswith(".py"):
        subprocess.run(["ruff", "format", "--quiet", path], check=False)
except (ValueError, OSError):
    pass
sys.exit(0)
""")
    write(home / "settings.json", json.dumps({
        "model": "opus",
        "hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [
            {"type": "command", "command": "python ~/.claude/hooks/format_changed.py", "timeout": 30}]}]},
    }, indent=2))
    write(home / "skills" / "deploy-staging" / "SKILL.md", """---
name: deploy-staging
description: Deploys the current branch to the staging environment and runs the smoke tests. Use when asked to deploy, ship or release to staging. Not for production, which goes through the release pipeline.
---
Build the image with `make image`, push it with `make push ENV=staging`, then
run `make smoke ENV=staging`. A smoke failure means the deploy is not done: read
the failing check's log and report it.
""")
    write(home / "agents" / "renamer.md", """---
name: renamer
description: Renames files and symbols across the repository to a given naming rule, and updates every import that refers to them. Use when a rename touches more than a handful of files.
model: haiku
tools: Read, Edit, Grep, Glob, Bash
---
You apply one naming rule across the repository. The delegation message gives
the rule and the scope.

Find every occurrence with Grep before changing anything, so the count is known.
Change files in place. After the last change, search again for the old name and
report what is left: a remaining occurrence is either an exception to the rule
or a miss, and the main session needs to know which.

Return the count changed, the files touched, and any occurrence you left alone
with the reason.
""")
    session(home / "projects" / "billing" / "s1.jsonl", "claude-opus-5-5",
            {"deploy-staging": 5}, {"renamer": 6}, requests=50, prompt_tokens=60000)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    out = pathlib.Path(sys.argv[1])
    planted(out / "planted")
    clean(out / "clean")
    print(f"built {out / 'planted'} and {out / 'clean'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
