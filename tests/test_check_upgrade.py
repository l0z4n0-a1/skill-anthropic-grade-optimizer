"""Tests for evals/check_upgrade.py, the oracle for the `planted` fixture after an upgrade.

Each test builds a fresh `planted` fixture under a temporary directory with evals/build_fixtures.py, edits it the way an
upgrade could, and reads what the oracle says. The null baseline (an untouched build) must fail all ten defect
checks; a hand-fixed copy must pass all of them; and each fix variation here pins one judgment the oracle makes.
Run: python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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
if "git" in command and "push" in command and command.split()[-1].lstrip("+").split(":")[-1].split("/")[-1] == "main":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": "no pushes to main"}}))
sys.exit(0)
'''

# deny rules that together block every push-to-main form the oracle tries and let the branches through
PUSH_RULES = ["Bash(git push * main)", "Bash(git push * +main)", "Bash(git push * HEAD:main)", "Bash(git push * HEAD:refs/heads/main)",
              "Bash(git -C * push * main)"]

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

    def test_a_disabled_hook_does_not_count(self):
        write(self.home / "hooks" / "guard_main.py", GOOD_GUARD)
        self.assertTrue(self.d1()[0])
        self.settings(lambda d: d.update(disableAllHooks=True))
        ok, why = self.d1()
        self.assertFalse(ok)
        self.assertIn("no enabled PreToolUse hook", why)
        self.assertNotFixed("D1")  # the same through the full check
        self.settings(lambda d: d.update(disableAllHooks=False))
        self.assertTrue(self.d1()[0])
        local = self.project / ".claude" / "settings.local.json"
        write(local, json.dumps({"disableAllHooks": True}))  # a later file wins
        self.assertFalse(self.d1()[0])
        local.unlink()
        group = lambda d: d["hooks"]["PreToolUse"][0]  # noqa: E731
        hook = lambda d: d["hooks"]["PreToolUse"][0]["hooks"][0]  # noqa: E731
        for pick in (group, hook):
            for flag in ({"disabled": True}, {"enabled": False}):
                self.settings(lambda d: pick(d).update(flag))
                self.assertFalse(self.d1()[0], (pick, flag))
                self.settings(lambda d: [pick(d).pop(k) for k in flag])
                self.assertTrue(self.d1()[0])

    def test_deny_rules_that_cover_the_push_forms_pass_with_the_hook_disabled_and_a_bare_push_is_left_to_the_hook(self):
        self.assertNotIn("git push", check_upgrade.MUST_BLOCK)  # not testable: it is only wrong on main
        self.assertFalse(any(check_upgrade.deny_matches(r, "git push") for r in PUSH_RULES))
        self.settings(lambda d: d.update(permissions={"deny": PUSH_RULES}, disableAllHooks=True))
        results = self.results()
        self.assertFixed("D1", results)
        self.assertFixed("D2", results)  # the exit-1 guard does not run
        self.settings(lambda d: d.update(permissions={"deny": PUSH_RULES[:-1]}))
        self.assertNotFixed("D1")  # one of the forms is open

    def test_a_hook_is_run_as_configured_with_its_arguments_and_not_as_the_bare_script(self):
        write(self.home / "hooks" / "guard_main.py", GOOD_GUARD.replace("command = ", 'if "--enforce" not in sys.argv:\n    sys.exit(0)\ncommand = ', 1))
        self.assertNotFixed("D1")  # the script is right but the configured command does not ask it to enforce
        self.sub(self.home / "settings.json", "guard_main.py", "guard_main.py --enforce")
        self.assertFixed("D1")
        self.sub(self.home / "settings.json", "~/.claude/hooks/guard_main.py", "$HOME/.claude/hooks/guard_main.py")
        self.assertFixed("D1")  # $HOME is the fixture's home

    def configure(self, command, **hook):
        write(self.home / "hooks" / "guard_main.py", GOOD_GUARD)
        self.settings(lambda d: d["hooks"]["PreToolUse"][0]["hooks"][0].update(command=command, **hook))

    def d1(self):
        """D1 on the fixture in place, without the copy and the fresh build the full check makes (the guard is the same)."""
        return check_upgrade.Checks(check_upgrade.Setup(self.fx, self.fx), self.fx).d1()

    def not_exercised(self, command, *words):
        self.configure(command)
        ok, why = self.d1()
        self.assertFalse(ok, f"{command}: {why}")
        self.assertIn("not exercised: ", why, command)
        for word in words:
            self.assertIn(word, why, command)

    def test_no_shell_is_used_so_syntax_variables_and_other_programs_are_not_exercised_and_not_fixed(self):
        marker = self.out / "ran.txt"
        script = "~/.claude/hooks/guard_main.py"
        self.not_exercised(f"cd /no/such/folder && python {script}", "starts with `cd`")
        self.not_exercised(f"python {script} && python -c \"open('{marker.as_posix()}', 'w')\"", "shell syntax")
        self.not_exercised(f"python {script}; touch {marker.as_posix()}", "shell syntax")
        self.not_exercised(f"python {script} > {marker.as_posix()}", "shell syntax")
        self.not_exercised(f"python {script} | cat", "shell syntax")
        self.not_exercised("python $OTHER/.claude/hooks/guard_main.py", "variable other than HOME")
        self.not_exercised('python "${XDG_DIR}/guard_main.py"', "variable other than HOME")
        self.not_exercised("python $HOMEDIR/.claude/hooks/guard_main.py", "variable other than HOME")  # not $HOME
        self.not_exercised(f"bash {script}", "starts with `bash`")
        self.not_exercised("~/.claude/hooks/guard_main.sh", "starts with")
        self.not_exercised(f"python3.11 {script}", "starts with `python3.11`")
        self.not_exercised(f"node {script}", "starts with `node`")
        self.not_exercised(f"py -2 {script}", "option `-2`")
        self.not_exercised("python -c \"import sys\"", "option `-c`")
        self.not_exercised("python", "no script")
        self.not_exercised("python 'unclosed", "cannot be parsed")
        self.not_exercised("python ~/.claude/hooks/missing.py", "not a file")
        self.assertFalse(marker.exists(), "something outside the one script ran")

    def test_home_and_project_dir_variables_resolve_to_the_fixture_and_py_3_loses_its_flag(self):
        guard = "/.claude/hooks/guard_main.py"
        for command in (f"python $HOME{guard}", f"python ${{HOME}}{guard}", f'python "$HOME{guard}"', f"python3 ${{HOME}}{guard} --x",
                        f"python $CLAUDE_PROJECT_DIR/../home{guard}", f'python "${{CLAUDE_PROJECT_DIR}}/../home{guard}"',
                        f"py -3 ~{guard}", f"py -3 $HOME{guard}", f"PY.EXE -3 ${{HOME}}{guard}"):
            self.configure(command)
            ok, why = self.d1()
            self.assertTrue(ok, f"{command}: {why}")
        setup = check_upgrade.Setup(self.fx, self.fx)
        plan = check_upgrade.plan_command(setup, f"py -3 $HOME{guard} --home $HOME --proj ${{CLAUDE_PROJECT_DIR}} --other $ELSE")
        self.assertEqual(plan["note"], "")
        self.assertEqual(plan["argv"][0], sys.executable)
        self.assertEqual(pathlib.Path(plan["argv"][1]), self.home / "hooks" / "guard_main.py")
        self.assertEqual([pathlib.Path(a) for a in plan["argv"][3:4] + plan["argv"][5:6]], [self.fx / "home", self.project])
        self.assertEqual(plan["argv"][-1], "$ELSE")  # an argument's other variables are left as written
        self.assertIn("-3", check_upgrade.plan_command(setup, f"py -3 -3 {guard}")["note"])  # only the first -3 is dropped
        for command in (f"py -3 $HOME{guard} && echo", "py -3 ~/x.sh", f"cd $HOME && python $HOME{guard}"):
            self.assertIn("not exercised", check_upgrade.plan_command(setup, command)["note"], command)

    def test_python_python3_and_py_are_run_with_this_interpreter_and_quotes_and_the_home_are_resolved(self):
        for name in ("python", "python3", "py", "PYTHON.EXE", "/usr/bin/python3"):
            self.configure(f"{name} ~/.claude/hooks/guard_main.py")
            self.assertFixed("D1")
        self.configure('python "~/.claude/hooks/guard_main.py" --x')  # a quoted word is one word; ~ is the home even inside quotes here
        plan = check_upgrade.plan_command(check_upgrade.Setup(self.fx, self.fx), 'python "~/.claude/hooks/guard_main.py" --x "a b"')
        self.assertEqual(plan["argv"][0], sys.executable)
        self.assertEqual(pathlib.Path(plan["argv"][1]), self.home / "hooks" / "guard_main.py")
        self.assertEqual(plan["argv"][2:], ["--x", "a b"])
        plan = check_upgrade.plan_command(check_upgrade.Setup(self.fx, self.fx), "python guard.py $HOME ~x")
        self.assertIn("not exercised", plan["note"])  # a relative script is looked up in the project, and it is not there

    def test_a_guard_outside_the_fixture_is_reported_and_not_executed(self):
        marker = self.out / "ran.txt"
        outside = self.out / "elsewhere" / "guard.py"
        write(outside, GOOD_GUARD.replace("command = ", f"open({str(marker)!r}, 'w').close()\ncommand = ", 1))
        self.sub(self.home / "settings.json", "python ~/.claude/hooks/guard_main.py", f"python {outside.as_posix()}")
        ok, why = self.results()["D1"]
        self.assertFalse(ok)
        self.assertIn("outside the fixture", why)
        self.assertFalse(marker.exists(), "the oracle ran a script that is not in the fixture")

    def test_a_script_that_is_a_link_to_a_file_outside_the_fixture_is_not_executed_either(self):
        marker = self.out / "ran.txt"
        outside = self.out / "elsewhere" / "guard.py"
        write(outside, GOOD_GUARD.replace("command = ", f"open({str(marker)!r}, 'w').close()\ncommand = ", 1))
        (self.home / "hooks" / "guard_main.py").unlink()
        try:
            (self.home / "hooks" / "guard_main.py").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("this system will not create symlinks for the test")
        ok, why = self.results()["D1"]
        self.assertFalse(ok)
        self.assertIn("outside the fixture", why)
        self.assertFalse(marker.exists())

    def test_inside_resolves_links_before_judging_where_a_path_is(self):
        root = self.fx
        self.assertTrue(check_upgrade.inside(root / "home" / "x.py", root))
        self.assertTrue(check_upgrade.inside(root, root))
        self.assertFalse(check_upgrade.inside(self.out / "elsewhere" / "x.py", root))
        self.assertFalse(check_upgrade.inside(root.parent / (root.name + "-sibling") / "x.py", root))  # a shared name prefix is not inside
        self.assertFalse(check_upgrade.inside(root / "home" / ".." / ".." / "x.py", root))
        real = os.path.realpath
        link = root / "home" / "link.py"
        with mock.patch.object(check_upgrade.os.path, "realpath", lambda p: str(self.out / "elsewhere" / "x.py") if p == link else real(p)):
            self.assertFalse(check_upgrade.inside(link, root))  # a link in the fixture that leads out

    def test_a_guard_runs_with_a_minimal_environment_and_the_fixture_home(self):
        guard = GOOD_GUARD.replace("command = ", 'import os\nhome = os.environ.get("HOME", "").replace("\\\\", "/")\n'
                                   'if "ORACLE_TEST_SECRET" in os.environ or not home.endswith("/home"):\n    sys.exit(0)  # fail open: it saw too much\ncommand = ', 1)
        write(self.home / "hooks" / "guard_main.py", guard)
        with mock.patch.dict(os.environ, {"ORACLE_TEST_SECRET": "hunter2", "ANTHROPIC_API_KEY": "sk-test"}):
            self.assertFixed("D1")
            env = check_upgrade.minimal_env(check_upgrade.Setup(self.fx, self.fx))
        self.assertNotIn("ORACLE_TEST_SECRET", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(pathlib.Path(env["HOME"]), self.fx / "home")
        self.assertEqual(pathlib.Path(env["CLAUDE_PROJECT_DIR"]), self.project)

    def test_deny_rules_are_read_the_way_claude_code_reads_bash_rules(self):
        cases = [("Bash", "git push origin main", True), ("Bash(git push origin main)", "git push origin main", True),
                 ("Bash(git push origin main)", "git push origin +main", False), ("Bash(git push:*)", "git push origin x", True),
                 ("Bash(git push:*)", "git pushy", False), ("Bash(git push * main)", "git push --signed origin main", True),
                 ("Bash(git push * main)", "git push origin feature-main", False), ("Read(./.env)", "git push origin main", False)]
        for rule, command, expected in cases:
            self.assertEqual(check_upgrade.deny_matches(rule, command), expected, (rule, command))

    def test_a_deny_rule_for_one_branch_or_one_form_or_every_push_is_not_a_fix(self):
        for rules in (["Bash(git push origin feature-main)"], ["Bash(git push origin main)"], ["Bash(git push:*)"], ["Bash(git *)"]):
            shutil.rmtree(self.fx)
            build_fixtures.planted(self.fx)
            self.settings(lambda d: (d.update(permissions={"deny": rules}), d["hooks"].pop("PreToolUse")))
            results = self.results()
            self.assertNotFixed("D1", results)
            self.assertNotFixed("D2", results)
            self.assertIn("deny rules", results["D1"][1], rules)

    def test_a_deny_rule_with_the_hook_removed_fixes_both_and_with_the_broken_hook_kept_fixes_only_d1(self):
        self.settings(lambda d: d.update(permissions={"deny": PUSH_RULES}))
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
        short = ("# Billing service\n\nMoney is stored as integer cents everywhere, because two rounding bugs; Decimal at the API.\n"
                 "Tests run with `make test`; `docker compose up db`.\n")
        write(claude, short)  # the steps are out of CLAUDE.md, but nothing leads to docs/close.md
        self.assertNotFixed("D6")
        write(claude, short + "\nMonth-end close: see docs/close.md when asked.\n")  # named, not imported
        ok, why = self.results()["D6"]
        self.assertTrue(ok, why)
        self.assertIn("docs/close.md", why)

    def test_d6_does_not_pass_when_the_procedure_is_deleted_or_left_where_nothing_calls_it(self):
        claude = self.project / "CLAUDE.md"
        procedure = claude.read_text(encoding="utf-8")
        short = "# Billing service\n\nMoney is stored as integer cents; Decimal at the API; rounding.\n`make test`, `docker compose up db`.\n"
        write(claude, short)
        ok, why = self.results()["D6"]
        self.assertFalse(ok, why)
        self.assertIn("no skill or file", why)
        write(self.home / "agents" / "notes.md", procedure)  # an agent file is not a place the steps can be called from
        self.assertNotFixed("D6")
        write(self.home / "skills" / "month-end-close" / "SKILL.md",
              "---\nname: month-end-close\ndescription: Runs the month-end close. Use on the first business day of a month.\n---\n" + procedure)
        ok, why = self.results()["D6"]
        self.assertTrue(ok, why)
        self.assertIn("skill", why)

    def test_d6_counts_a_skill_only_when_its_frontmatter_has_a_name_and_a_description(self):
        claude = self.project / "CLAUDE.md"
        procedure = claude.read_text(encoding="utf-8").split("## Month-end close procedure")[1].split("CRITICAL")[0]
        write(claude, CLAUDE_MD.replace("Month-end close has a skill: ask for it by name.\n", ""))
        skill = self.home / "skills" / "scratch" / "SKILL.md"
        for head in ("", "---\nname: scratch\n---\n", "---\ndescription: only this\n---\n", "---\nname:\ndescription: x\n---\n"):
            write(skill, head + procedure)
            self.assertNotFixed("D6")
        write(skill, "---\nname: scratch\ndescription: Runs the month-end close.\n---\n" + procedure)
        self.assertFixed("D6")

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

    def test_s5_allows_new_skills_and_hooks_and_removing_a_defect_file_but_not_other_new_files(self):
        self.fix_all()
        self.assertFixed("S5")  # fix_all adds a skill and rewrites defect files
        write(self.home / "hooks" / "lib" / "helper_lib.py", "X = 1\n")
        self.assertFixed("S5")
        (self.home / "agents" / "helper.md").unlink()  # a defect file may go
        self.assertFixed("S5")
        for stray in (self.project / "docs" / "close.md", self.project / "src" / "x.py", self.home / "agents" / "new.md",
                      self.home / "notes.txt"):
            write(stray, "x\n")
            ok, why = self.results()["S5"]
            self.assertFalse(ok, stray)
            self.assertIn("new files that are not skills, hooks or named in CLAUDE.md", why)
            self.assertIn(stray.name, why)
            stray.unlink()
        self.assertFixed("S5")

    def test_s5_allows_a_new_project_file_that_claude_md_points_to(self):
        self.fix_all()
        claude = self.project / "CLAUDE.md"
        steps = "\n".join(check_upgrade.MONTH_END) + "\n"
        write(self.project / "docs" / "close.md", steps)
        self.assertNotFixed("S5")  # not named yet
        write(claude, claude.read_text(encoding="utf-8") + "\nMonth-end close: see docs/close.md when asked.\n")
        ok, why = self.results()["S5"]
        if not ok:  # CLAUDE.md is a defect file, so editing it is allowed; only the new file is judged
            self.fail(why)

    def test_s5_a_named_project_file_without_the_month_end_steps_is_a_stray(self):
        self.fix_all()
        claude = self.project / "CLAUDE.md"
        write(claude, claude.read_text(encoding="utf-8") + "\nSee docs/close.md, docs/other.md and src/x.py.\n")
        write(self.project / "docs" / "close.md", "make export-ledger and make lock-month only\n")  # 2 of the 6 markers
        write(self.project / "docs" / "other.md", "unrelated\n")
        write(self.project / "src" / "x.py", "X = 1\n")
        ok, why = self.results()["S5"]
        self.assertFalse(ok)
        for stray in ("close.md", "other.md", "x.py"):
            self.assertIn(stray, why)
        write(self.project / "docs" / "close.md", "\n".join(check_upgrade.MONTH_END))  # now it is D6's target
        for stray in ("docs/other.md", "src/x.py"):
            (self.project / stray).unlink()
        self.assertFixed("S5")

    def test_s5_fails_an_edited_file_that_no_defect_lives_in_and_a_defect_file_is_not_exempt_for_its_neighbours(self):
        self.fix_all()
        transcript = self.home / "projects" / "billing" / "s1.jsonl"
        write(transcript, transcript.read_text(encoding="utf-8") + '{"edited": true}\n')
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
