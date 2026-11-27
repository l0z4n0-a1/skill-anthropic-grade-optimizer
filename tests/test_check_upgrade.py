"""Tests for evals/check_upgrade.py, the oracle for the `planted` fixture after an upgrade.

Each test builds a fresh `planted` fixture under a temporary directory with evals/build_fixtures.py, edits it the way an
upgrade could, and reads what the oracle says. The null baseline (an untouched build) must fail all ten defect
checks; a hand-fixed copy must pass all of them; and each fix variation here pins one judgment the oracle makes.
Run: python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import build_fixtures  # noqa: E402
import check_upgrade  # noqa: E402

GOOD_GUARD = '''#!/usr/bin/env python3
"""Blocks a push to main."""
import json
import re
import sys

command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
if re.search(r"\\bgit\\b.*\\bpush\\b", command) and re.search(r"(?<![\\w-])main(?![\\w-])", command):
    print("Pushing to main is not allowed.", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
'''

SUBSTRING_GUARD = GOOD_GUARD.replace('re.search(r"(?<![\\w-])main(?![\\w-])", command)', '"main" in command')

JSON_GUARD = '''import json
import sys

command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
if "git" in command and "push" in command and command.split()[-1].split(":")[-1] == "main":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": "no pushes to main"}}))
sys.exit(0)
'''

CLAUDE_MD = """# Billing service

Python 3.12 service that issues invoices. Tests run with `make test`; the suite
needs the local Postgres from `docker compose up db`.

Open a pull request for every change; a hook blocks pushes to main.

Money is stored as integer cents everywhere. The `Decimal` type appears only at
the API boundary, because two rounding bugs came from mixing the two.

Month-end close has a skill: ask for it by name.
"""

HELPER = """---
name: helper
description: Answers short questions about how this repository is laid out, where a symbol is defined and which tests cover it. Use when a question needs reading several files.
model: haiku
tools: Read, Grep, Glob
---
You answer questions about this repository by reading it; you do not change files or run commands. Find the
relevant files with Grep and Glob, read only what the question needs, and answer in a few sentences. Return the
answer first, then the file paths you relied on, and say plainly when you could not find something.
"""


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class OracleTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = pathlib.Path(tmp.name).resolve()
        build_fixtures.planted(self.out / "planted")
        self.fx = self.out / "planted"
        self.home, self.project = self.fx / "home" / ".claude", self.fx / "project"

    # -- editing the fixture

    def settings(self, change=None):
        path = self.home / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if change:
            change(data)
        write(path, json.dumps(data, indent=2))

    def sub(self, path: pathlib.Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        write(path, text.replace(old, new))

    def fix_all(self):
        write(self.home / "hooks" / "guard_main.py", GOOD_GUARD)
        self.settings(lambda d: d["hooks"].pop("PostToolUse"))
        procedure = (self.project / "CLAUDE.md").read_text(encoding="utf-8").split("## Month-end close procedure")[1].split("CRITICAL")[0]
        write(self.project / "CLAUDE.md", CLAUDE_MD)
        write(self.home / "skills" / "month-end-close" / "SKILL.md",
              "---\nname: month-end-close\ndescription: Runs the month-end close. Use on the first business day of a month.\n---\n" + procedure)
        write(self.home / "agents" / "helper.md", HELPER)
        self.sub(self.home / "agents" / "renamer.md", "model: opus\neffort: max\n", "model: haiku\n")
        self.sub(self.home / "skills" / "deploy-staging" / "SKILL.md", "Use when asked to deploy, ship or release to staging.",
                 "Use when asked to deploy to staging. For a release, use release-staging.")
        write(self.home / "skills" / "audit-readonly" / "SKILL.md", """---
name: audit-readonly
description: Read-only audit of the repository's dependency licences. Use when asked which licences the dependencies carry.
allowed-tools: Read, Grep, Glob
---
`allowed-tools` pre-approves these tools; it does not restrict the skill, so do not modify files or run commands
here, and say so if a step seems to need it.

List each dependency from the lock file with its declared licence. Flag any
licence that is not MIT, BSD or Apache-2.0, and say where the declaration was
found.
""")
        write(self.home / "skills" / "repo-stats" / "SKILL.md", """---
name: repo-stats
description: Reports the size of the codebase by language. Use when asked how big the repository is or how the code splits across languages.
---
Run `git ls-files | xargs wc -l` and group the counts by file extension. Present the totals as a table.
""")

    def results(self):
        return {label: (ok, why) for label, ok, why in check_upgrade.check(self.fx)}

    def assertFixed(self, label, results=None):
        ok, why = (results or self.results())[label]
        self.assertTrue(ok, f"{label}: {why}")

    def assertNotFixed(self, label, results=None):
        ok, why = (results or self.results())[label]
        self.assertFalse(ok, f"{label} should not pass: {why}")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "evals" / "check_upgrade.py"), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    # -- the two anchors

    def test_a_fresh_build_fails_every_defect_check_and_keeps_every_sound_thing(self):
        results = self.results()
        for n in range(1, 11):
            self.assertNotFixed(f"D{n}", results)
        for n in range(1, 6):
            self.assertFixed(f"S{n}", results)

    def test_the_command_line_on_a_fresh_build_is_exit_1_with_ten_not_fixed_lines(self):
        done = self.run_cli(self.fx)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(len(re.findall(r"^D\d+ not fixed: ", done.stdout, re.M)), 10)
        self.assertEqual(len(re.findall(r"^S\d+ kept: ", done.stdout, re.M)), 5)
        self.assertEqual(self.run_cli(self.out).returncode, 1)  # the output folder that holds planted/ works too

    def test_a_hand_fixed_copy_passes_every_check_and_the_command_line_exits_0(self):
        self.fix_all()
        results = self.results()
        for label, (ok, why) in results.items():
            self.assertTrue(ok, f"{label}: {why}")
        done = self.run_cli(self.fx)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("defects fixed: 10 of 10; sound things kept: 5 of 5", done.stdout)

    def test_the_oracle_does_not_modify_the_fixture(self):
        self.fix_all()
        snapshot = lambda: {p: p.read_bytes() for p in self.fx.rglob("*") if p.is_file()}  # noqa: E731
        before = snapshot()
        self.run_cli(self.fx)
        self.assertEqual(snapshot(), before)

    def test_usage_errors_are_exit_2(self):
        for args in ((), ("--help",), (self.fx, self.fx), (self.out / "missing",), (self.home,)):
            done = self.run_cli(*args)
            self.assertEqual(done.returncode, 2, f"{args}: {done.stdout}{done.stderr}")
            self.assertEqual(done.stdout, "")

    # -- D1 and D2: behavior

    def test_a_guard_that_matches_text_and_blocks_a_branch_named_domain_fix_is_not_a_fix(self):
        write(self.home / "hooks" / "guard_main.py", SUBSTRING_GUARD)
        results = self.results()
        self.assertNotFixed("D2", results)
        self.assertNotFixed("D1", results)
        self.assertIn("domain-fix", results["D2"][1])

    def test_a_guard_that_denies_in_json_on_exit_0_is_a_fix(self):
        write(self.home / "hooks" / "guard_main.py", JSON_GUARD)
        results = self.results()
        self.assertFixed("D1", results)
        self.assertFixed("D2", results)

    def test_a_hook_whose_matcher_misses_bash_does_not_enforce(self):
        write(self.home / "hooks" / "guard_main.py", GOOD_GUARD)
        self.settings(lambda d: d["hooks"]["PreToolUse"][0].update(matcher="Edit|Write"))
        self.assertNotFixed("D1")

    def test_a_deny_rule_with_the_hook_removed_fixes_both_and_with_the_broken_hook_kept_fixes_only_d1(self):
        self.settings(lambda d: d.update(permissions={"deny": ["Bash(git push origin main)"]}))
        results = self.results()
        self.assertFixed("D1", results)
        self.assertNotFixed("D2", results)  # the exit-1 guard is still wired
        self.settings(lambda d: d["hooks"].pop("PreToolUse"))
        results = self.results()
        self.assertFixed("D1", results)
        self.assertFixed("D2", results)

    def test_removing_the_hook_with_nothing_in_its_place_fixes_d2_nowhere_and_d1_not_at_all(self):
        self.settings(lambda d: d["hooks"].pop("PreToolUse"))
        results = self.results()
        self.assertNotFixed("D1", results)
        self.assertNotFixed("D2", results)

    # -- D3, D4

    def test_d3_needs_the_key_spelled_right_and_a_recognised_model(self):
        helper = self.home / "agents" / "helper.md"
        self.sub(helper, "modle: haiku", "model: gpt-4")
        self.assertNotFixed("D3")
        self.sub(helper, "model: gpt-4", "model: haiku")
        self.assertFixed("D3")
        self.sub(helper, "model: haiku", "model: claude-haiku-5-5")
        self.assertFixed("D3")

    def test_d3_and_d4_accept_removing_the_agent(self):
        (self.home / "agents" / "helper.md").unlink()
        results = self.results()
        self.assertFixed("D3", results)
        self.assertFixed("D4", results)

    def test_d4_needs_a_real_description_a_prompt_a_return_and_tools(self):
        write(self.home / "agents" / "helper.md", HELPER.replace("tools: Read, Grep, Glob\n", ""))
        self.assertNotFixed("D4")
        write(self.home / "agents" / "helper.md", HELPER)
        self.assertFixed("D4")

    # -- D5 to D8

    def test_d5_accepts_a_removal_a_boundary_or_taking_one_off_the_model(self):
        dep, rel = self.home / "skills" / "deploy-staging" / "SKILL.md", self.home / "skills" / "release-staging" / "SKILL.md"
        self.assertNotFixed("D5")
        self.sub(rel, "description:", "disable-model-invocation: true\ndescription:")
        self.assertFixed("D5")
        self.sub(rel, "disable-model-invocation: true\n", "")
        self.assertNotFixed("D5")
        self.sub(rel, "Use when asked to release, deploy or ship to the staging environment.",
                 "Not for plain deploys: those go through deploy-staging.")
        self.assertFixed("D5")
        rel.unlink()
        self.assertFixed("D5")

    def test_d6_follows_an_import_because_an_imported_file_loads_every_session(self):
        claude = self.project / "CLAUDE.md"
        procedure = claude.read_text(encoding="utf-8")
        write(self.project / "docs" / "close.md", procedure)
        write(claude, "# Billing service\n\nMoney is stored as integer cents everywhere, because two rounding bugs; Decimal at the API.\n"
                      "Tests run with `make test`; `docker compose up db`.\n\n@docs/close.md\n")
        self.assertNotFixed("D6")
        write(claude, "# Billing service\n\nMoney is stored as integer cents everywhere, because two rounding bugs; Decimal at the API.\n"
                      "Tests run with `make test`; `docker compose up db`.\n")
        ok, why = self.results()["D6"]
        self.assertTrue(ok, why)
        self.assertIn("docs/close.md", why)

    def test_d7_rejects_a_reworded_false_claim_and_accepts_the_truth_or_a_removal(self):
        skill = self.home / "skills" / "audit-readonly" / "SKILL.md"
        self.sub(skill, "This skill is read-only: because of `allowed-tools`, it cannot modify files or\nrun commands, so it is safe to use on a production checkout.",
                 "The `allowed-tools` field limits this skill to reading, which makes it safe on production.")
        self.assertNotFixed("D7")
        self.sub(skill, "The `allowed-tools` field limits this skill to reading, which makes it safe on production.",
                 "`allowed-tools` only pre-approves these tools; it does not restrict the skill.")
        self.assertFixed("D7")
        self.sub(skill, "`allowed-tools` only pre-approves these tools; it does not restrict the skill.",
                 "This skill is read-only: `disallowed-tools` removes the editing and shell tools\nuntil the next user message.")
        self.assertFixed("D7")  # disallowed-tools does restrict; "allowed-tools" inside it is not the false claim
        self.sub(skill, "This skill is read-only: `disallowed-tools` removes the editing and shell tools\nuntil the next user message.", "")
        self.assertFixed("D7")

    def test_d8_needs_the_reading_gone_and_something_to_count_with(self):
        skill = self.home / "skills" / "repo-stats" / "SKILL.md"
        write(skill, "---\nname: repo-stats\ndescription: Reports the size of the codebase by language.\n---\nReport the totals as a table.\n")
        self.assertNotFixed("D8")
        write(skill, "---\nname: repo-stats\ndescription: Reports the size of the codebase by language.\n---\nRun `tokei` and report its table.\n")
        self.assertFixed("D8")
        skill.unlink()
        self.assertFixed("D8")

    # -- D9, D10

    def test_d9_accepts_the_script_created_or_the_entry_removed_and_refuses_broken_settings(self):
        self.assertNotFixed("D9")
        write(self.home / "hooks" / "format_changed.py", "import sys\nsys.exit(0)\n")
        self.assertFixed("D9")
        (self.home / "hooks" / "format_changed.py").unlink()
        self.settings(lambda d: d["hooks"].pop("PostToolUse"))
        self.assertFixed("D9")
        write(self.home / "settings.json", "{ not json")
        self.assertNotFixed("D9")

    def test_d10_wants_the_renamer_off_the_top_tier_or_at_low_or_medium_effort(self):
        renamer = self.home / "agents" / "renamer.md"
        self.sub(renamer, "effort: max", "effort: high")
        self.assertNotFixed("D10")  # opus at high is still the top tier above medium
        self.sub(renamer, "effort: high", "effort: medium")
        self.assertFixed("D10")
        self.sub(renamer, "effort: medium", "effort: low")
        self.assertFixed("D10")
        self.sub(renamer, "effort: low\n", "")
        self.assertNotFixed("D10")  # opus with the effort unset
        self.sub(renamer, "model: opus", "model: claude-opus-5-5\neffort: high")
        self.assertNotFixed("D10")  # an opus id is opus
        self.sub(renamer, "model: claude-opus-5-5", "model: sonnet")
        self.assertFixed("D10")  # off the top tier, whatever the effort
        self.sub(renamer, "model: sonnet\n", "")  # inherits the session model, which is opus in settings.json
        self.assertNotFixed("D10")
        renamer.unlink()
        self.assertFixed("D10")

    # -- survival

    def test_removing_a_sound_rule_fails_the_matching_survival_check_and_only_it(self):
        self.fix_all()
        claude = self.project / "CLAUDE.md"
        original = claude.read_text(encoding="utf-8")
        cases = {
            "S1": original.replace("Money is stored as integer cents everywhere. The `Decimal` type appears only at\nthe API boundary, because two rounding bugs came from mixing the two.\n", ""),
            "S2": original.replace("Tests run with `make test`; the suite\nneeds the local Postgres from `docker compose up db`.", ""),
        }
        for label, text in cases.items():
            self.assertNotEqual(text, original, label)
            write(claude, text)
            results = self.results()
            self.assertEqual([l for l in results if l.startswith("S") and not results[l][0]], [label], results[label])
        write(claude, original)
        self.sub(self.home / "agents" / "renamer.md", "Return the count changed", "Return nothing")
        results = self.results()
        self.assertEqual([l for l in results if not results[l][0]], ["S3"], results["S3"])
        self.sub(self.home / "agents" / "renamer.md", "Return nothing", "Return the count changed")
        self.sub(self.home / "skills" / "deploy-staging" / "SKILL.md", "make smoke ENV=staging", "make check")
        self.sub(self.home / "skills" / "release-staging" / "SKILL.md", "scripts/release.sh staging", "scripts/release.sh staging")
        results = self.results()
        self.assertEqual([l for l in results if not results[l][0]], ["S4"], results["S4"])

    def test_deleting_session_history_fails_s5_and_a_changed_timestamp_does_not(self):
        self.fix_all()
        transcript = self.home / "projects" / "billing" / "s1.jsonl"
        text = transcript.read_text(encoding="utf-8")
        write(transcript, re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z", "2001-01-01T00:00:00.000Z", text))
        self.assertFixed("S5")
        transcript.unlink()
        ok, why = self.results()["S5"]
        self.assertFalse(ok)
        self.assertIn("s1.jsonl", why)

    def test_main_prints_one_line_per_check_and_returns_the_exit_code(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_upgrade.main([str(self.fx)])
        self.assertEqual(code, 1)
        self.assertEqual([line.split()[0] for line in out.getvalue().splitlines()[:15]],
                         [f"D{i}" for i in range(1, 11)] + [f"S{i}" for i in range(1, 6)])


if __name__ == "__main__":
    unittest.main()
