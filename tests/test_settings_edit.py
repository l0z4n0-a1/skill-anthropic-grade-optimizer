"""Tests for scripts/settings_edit.py: edits to a settings file made without printing the rest of it.

Every test writes its own settings file under a temporary directory. A secret planted in the file must never
reach stdout or stderr. Run: python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import measure  # noqa: E402
import settings_edit  # noqa: E402

SECRET = "sk-SECRET-TOKEN-123"
OTHER_HOOK = f"python ~/.claude/hooks/other.py --token {SECRET}"

START = {
    "model": "opus",
    "env": {"API_KEY": SECRET},
    "permissions": {"allow": ["Bash(make test)"], "defaultMode": "default"},
    "hooks": {
        "PostToolUse": [{"matcher": "Edit|Write", "hooks": [
            {"type": "command", "command": "python ~/.claude/hooks/fmt.py", "timeout": 30},
            {"type": "command", "command": OTHER_HOOK}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python ~/.claude/hooks/guard.py"}]}]},
    "zeta": 1, "alpha": {"nested": [1, 2, {"x": None}]},
}


class EditTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name).resolve()
        self.file = self.base / "settings.json"
        self.write(START)

    def write(self, data, **kw):
        self.file.write_text(json.dumps(data, indent=kw.get("indent", 2), ensure_ascii=False) + "\n", encoding="utf-8")

    def data(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def run_edit(self, *args, file=None, commands_listed=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = settings_edit.main([str(file or self.file), *map(str, args)])
            except SystemExit as exc:
                code = exc.code
        if not commands_listed:  # a refusal lists the candidate hook commands, as documented; nothing else may leak
            self.assertNotIn(SECRET, out.getvalue() + err.getvalue(), "a secret from the file was printed")
        return code, out.getvalue(), err.getvalue()

    # -- add-hook

    def test_add_hook_creates_the_event_and_the_shape_measure_parses(self):
        code, out, err = self.run_edit("add-hook", "--event", "Stop", "--command", "python ~/.claude/hooks/done.py", "--timeout", 20)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.data()["hooks"]["Stop"], [{"hooks": [{"type": "command", "command": "python ~/.claude/hooks/done.py", "timeout": 20}]}])
        self.assertIn("change: hooks.Stop (hook added)", out)
        self.assertIn("before: (absent)", out)
        self.assertNotIn("PostToolUse", out)

    def test_add_hook_refuses_an_undocumented_event_unless_told(self):
        before = self.file.read_bytes()
        code, out, err = self.run_edit("add-hook", "--event", "PreToolUses", "--command", "python g.py")
        self.assertEqual(code, 2)
        self.assertIn("not a documented hook event", err + out)
        self.assertEqual(self.file.read_bytes(), before)
        code, out, err = self.run_edit("add-hook", "--event", "PreToolUses", "--command", "python g.py", "--allow-unknown-event")
        self.assertEqual(code, 0, err)
        self.assertIn("PreToolUses", self.data()["hooks"])

    def test_add_hook_joins_the_group_with_the_same_matcher_and_is_idempotent(self):
        args = ("add-hook", "--event", "PreToolUse", "--matcher", "Bash", "--command", "python ~/.claude/hooks/g2.py",
                "--on-failure", "block")
        self.assertEqual(self.run_edit(*args)[0], 0)
        groups = self.data()["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["hooks"][1], {"type": "command", "command": "python ~/.claude/hooks/g2.py", "onFailure": "block"})
        before = self.file.read_bytes()
        code, out, _ = self.run_edit(*args)
        self.assertEqual((code, "nothing to change" in out, self.file.read_bytes()), (0, True, before))
        self.run_edit("add-hook", "--event", "PreToolUse", "--matcher", "Edit", "--command", "x.py")
        self.assertEqual(len(self.data()["hooks"]["PreToolUse"]), 2)

    def test_what_add_hook_writes_is_read_back_by_measure(self):
        self.run_edit("add-hook", "--event", "PreToolUse", "--matcher", "Bash", "--command", "python ~/.claude/hooks/g2.py",
                      "--timeout", 7, "--on-failure", "block")
        home, project = self.base / "home" / ".claude", self.base / "proj"
        home.mkdir(parents=True)
        project.mkdir()
        (home / "settings.json").write_bytes(self.file.read_bytes())
        hooks = measure.build(home, project, 0, user_home=None)["settings"]["hooks"]
        added = next(h for h in hooks if "g2.py" in h["command"])
        self.assertEqual((added["event"], added["matcher"], added["timeout"], added["options"]), ("PreToolUse", "Bash", 7, {"onFailure": "block"}))

    # -- remove-hook, set-hook-option

    def test_remove_hook_takes_one_match_and_prunes_what_it_empties(self):
        code, out, err = self.run_edit("remove-hook", "--event", "PreToolUse", "--command-contains", "guard.py")
        self.assertEqual(code, 0, err)
        self.assertNotIn("PreToolUse", self.data()["hooks"])
        self.assertIn("hook removed", out)
        self.assertEqual(self.run_edit("remove-hook", "--event", "PostToolUse", "--command-contains", "fmt.py")[0], 0)
        self.assertEqual([h["command"] for h in self.data()["hooks"]["PostToolUse"][0]["hooks"]], [OTHER_HOOK])

    def test_remove_hook_refuses_zero_or_several_matches_and_lists_the_candidates(self):
        before = self.file.read_bytes()
        code, _, err = self.run_edit("remove-hook", "--event", "PostToolUse", "--command-contains", "nothing-like-this")
        self.assertEqual(code, 2)
        self.assertIn("no hook command", err)
        code, _, err = self.run_edit("remove-hook", "--event", "PostToolUse", "--command-contains", "python", commands_listed=True)
        self.assertEqual(code, 2)
        self.assertIn("2 hook commands", err)
        self.assertIn("fmt.py", err)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.run_edit("remove-hook", "--event", "Stop", "--command-contains", "x")[0], 2)  # no such event

    def test_set_hook_option_sets_and_clears_on_failure_and_sets_the_timeout(self):
        base = ("set-hook-option", "--event", "PreToolUse", "--command-contains", "guard.py")
        code, out, err = self.run_edit(*base, "--on-failure", "block", "--timeout", 9)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.data()["hooks"]["PreToolUse"][0]["hooks"][0],
                         {"type": "command", "command": "python ~/.claude/hooks/guard.py", "onFailure": "block", "timeout": 9})
        self.assertIn('"onFailure": "block"', out.split("after:")[1])
        self.assertNotIn("onFailure", out.split("after:")[0])  # `before` was copied, not mutated
        self.assertEqual(self.run_edit(*base, "--on-failure", "default")[0], 0)
        self.assertNotIn("onFailure", self.data()["hooks"]["PreToolUse"][0]["hooks"][0])
        self.assertIn("nothing to change", self.run_edit(*base, "--on-failure", "default")[1])
        self.assertEqual(self.run_edit(*base)[0], 2)  # neither option given

    # -- permissions

    def test_add_permission_is_idempotent_and_creates_the_list(self):
        args = ("add-permission", "--kind", "deny", "--rule", "Bash(git push origin main)")
        code, out, err = self.run_edit(*args)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.data()["permissions"]["deny"], ["Bash(git push origin main)"])
        self.assertEqual(self.data()["permissions"]["allow"], ["Bash(make test)"])
        self.assertIn("before: (absent)", out)
        before = self.file.read_bytes()
        self.assertIn("nothing to change", self.run_edit(*args)[1])
        self.assertEqual(self.file.read_bytes(), before)
        self.run_edit("add-permission", "--kind", "allow", "--rule", "Read")
        self.assertEqual(self.data()["permissions"]["allow"], ["Bash(make test)", "Read"])

    def test_remove_permission_removes_the_rule_and_is_quiet_when_it_is_absent(self):
        self.assertEqual(self.run_edit("remove-permission", "--kind", "allow", "--rule", "Bash(make test)")[0], 0)
        self.assertEqual(self.data()["permissions"]["allow"], [])
        code, out, _ = self.run_edit("remove-permission", "--kind", "allow", "--rule", "Bash(make test)")
        self.assertEqual((code, "not present" in out), (0, True))
        self.assertEqual(self.run_edit("add-permission", "--kind", "maybe", "--rule", "x")[0], 2)

    # -- set

    def test_set_uses_the_allowlist_measure_exposes_and_types_the_value(self):
        self.assertIs(settings_edit.SAFE_SETTINGS, measure.SAFE_SETTINGS)
        code, out, err = self.run_edit("set", "--key", "autoMemoryEnabled", "--value", "false")
        self.assertEqual(code, 0, err)
        self.assertIs(self.data()["autoMemoryEnabled"], False)
        self.run_edit("set", "--key", "cleanupPeriodDays", "--value", "14")
        self.assertEqual(self.data()["cleanupPeriodDays"], 14)
        code, out, _ = self.run_edit("set", "--key", "model", "--value", "sonnet")
        self.assertEqual((code, self.data()["model"]), (0, "sonnet"))
        self.assertIn('before: "opus"', out)
        self.assertIn('after: "sonnet"', out)
        self.assertIn("nothing to change", self.run_edit("set", "--key", "model", "--value", "sonnet")[1])

    def test_set_refuses_a_key_outside_the_allowlist_and_leaves_the_file_alone(self):
        before = self.file.read_bytes()
        for key in ("env", "apiKeyHelper", "hooks", "permissions"):
            code, _, err = self.run_edit("set", "--key", key, "--value", "x")
            self.assertEqual(code, 2, key)
            self.assertIn("is not a key this script sets", err)
        self.assertEqual(self.file.read_bytes(), before)

    # -- what is kept and what is printed

    def test_the_rest_of_the_file_is_kept_key_for_key_in_order_and_only_the_region_is_printed(self):
        before = self.data()
        code, out, _ = self.run_edit("add-permission", "--kind", "ask", "--rule", "Bash(git commit*)")
        self.assertEqual(code, 0)
        after = self.data()
        self.assertEqual(list(after), list(before))  # key order
        self.assertEqual({k: v for k, v in after.items() if k != "permissions"}, {k: v for k, v in before.items() if k != "permissions"})
        for text in ("API_KEY", "other.py", "zeta", "alpha", "nested"):
            self.assertNotIn(text, out)

    def test_indent_crlf_bom_and_a_missing_final_newline_are_kept(self):
        text = json.dumps(START, indent=4).replace("\n", "\r\n")
        self.file.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertEqual(self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")[0], 0)
        raw = self.file.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n    \"model\"", raw)
        self.assertNotIn(b"\n  \"", raw.replace(b"\r\n", b"\n").replace(b"\n    ", b""))
        self.assertFalse(raw.endswith(b"\n"))
        self.assertEqual(self.data_bom()["permissions"]["ask"], ["Read"])

    def data_bom(self):
        return json.loads(self.file.read_text(encoding="utf-8-sig"))

    def test_a_non_ascii_value_is_written_as_text_not_escapes(self):
        self.write({**START, "note": "café"})
        self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertIn("café", self.file.read_text(encoding="utf-8"))

    def test_dry_run_prints_the_change_and_writes_nothing(self):
        before = self.file.read_bytes()
        code, out, _ = self.run_edit("add-hook", "--event", "Stop", "--command", "x.py", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("after:", out)
        self.assertIn("dry run: nothing written", out)
        self.assertEqual(self.file.read_bytes(), before)

    # -- refusals

    def test_a_file_that_is_not_valid_json_is_exit_2_without_echoing_it_or_changing_it(self):
        self.file.write_text('{"env": {"k": "%s"}, oops' % SECRET, encoding="utf-8")
        before = self.file.read_bytes()
        code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)
        self.assertEqual(self.file.read_bytes(), before)

    def test_a_json_file_that_is_not_an_object_or_has_an_odd_shape_is_exit_2(self):
        self.file.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(self.run_edit("set", "--key", "model", "--value", "x")[0], 2)
        for bad, args in (({"hooks": []}, ("add-hook", "--event", "Stop", "--command", "x")),
                          ({"hooks": {"Stop": {"a": 1}}}, ("add-hook", "--event", "Stop", "--command", "x")),
                          ({"permissions": []}, ("add-permission", "--kind", "ask", "--rule", "x")),
                          ({"permissions": {"ask": "x"}}, ("add-permission", "--kind", "ask", "--rule", "x"))):
            self.write(bad)
            before = self.file.read_bytes()
            self.assertEqual(self.run_edit(*args)[0], 2, bad)
            self.assertEqual(self.file.read_bytes(), before)

    def test_a_bad_event_name_is_refused(self):
        self.assertEqual(self.run_edit("add-hook", "--event", "pre tool", "--command", "x")[0], 2)

    def test_a_missing_file_needs_create_and_dry_run_creates_nothing(self):
        missing = self.base / "new" / "settings.json"
        code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", file=missing)
        self.assertEqual(code, 2)
        self.assertIn("--create", err)
        self.assertFalse(missing.exists())
        self.assertEqual(self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", "--create", "--dry-run", file=missing)[0], 0)
        self.assertFalse(missing.exists())
        self.assertEqual(self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", "--create", file=missing)[0], 0)
        self.assertEqual(json.loads(missing.read_text(encoding="utf-8")), {"permissions": {"ask": ["Read"]}})

    def test_a_folder_is_refused(self):
        self.assertEqual(self.run_edit("set", "--key", "model", "--value", "x", file=self.base)[0], 2)

    # -- writing

    def test_a_failed_write_is_exit_1_the_file_is_as_it_was_and_no_temporary_file_stays(self):
        before = self.file.read_bytes()
        with mock.patch("backup.os.replace", side_effect=PermissionError(13, "denied")):
            code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertEqual(code, 1)
        self.assertIn("could not write", err)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["settings.json"])

    @unittest.skipUnless(hasattr(os, "fchmod"), "POSIX modes")
    def test_the_files_mode_is_kept(self):
        self.file.chmod(0o640)
        self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)

    def test_the_command_line_exit_codes(self):
        script = str(ROOT / "scripts" / "settings_edit.py")

        def run(*args):
            return subprocess.run([sys.executable, "-I", script, *map(str, args)], capture_output=True, text=True, encoding="utf-8")

        done = run(self.file, "add-permission", "--kind", "deny", "--rule", "Bash(rm -rf*)")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.data()["permissions"]["deny"], ["Bash(rm -rf*)"])
        self.assertEqual(run(self.file, "set", "--key", "env", "--value", "x").returncode, 2)
        self.assertEqual(run(self.file, "explode").returncode, 2)
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
