"""Tests for scripts/settings_edit.py: edits to a settings file made without printing the rest of it.

Every test writes its own settings file under a temporary directory. Secrets planted in the file, in hook commands
and elsewhere, must never reach stdout or stderr, whatever the operation or refusal.
Run: python -m unittest discover -s tests -t .
"""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import measure  # noqa: E402
import settings_edit  # noqa: E402

SECRETS = ["sk-SECRET-TOKEN-123", "hunter2-password", "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4MTIzNDU2", "bearer-secret-value", "env-key-value-9",
           "0123456789abcdef0123456789abcdef", "xapikey-planted-7", "envtok-planted-8", "kvsecret-planted-9"]
SECRET = SECRETS[0]
OTHER_HOOK = f"python ~/.claude/hooks/other.py --token {SECRET}"
URL_HOOK = f"curl -H 'Authorization: Bearer {SECRETS[3]}' https://user:{SECRETS[1]}@example.com/x"
ENV_HOOK = f"API_KEY={SECRETS[4]} python ~/.claude/hooks/env.py {SECRETS[2]} {SECRETS[5]}"
XKEY_HOOK = f'curl -H "X-Api-Key: {SECRETS[6]}" https://api.example.com/v1'  # quoted header
TOKEN_ENV_HOOK = f"TOKEN={SECRETS[7]} python ~/.claude/hooks/e2.py"  # env-prefixed
KV_HOOK = f"python ~/.claude/hooks/k.py api_key={SECRETS[8]}"  # key=value

START = {
    "model": "opus",
    "env": {"API_KEY": SECRET},
    "permissions": {"allow": ["Bash(make test)", f"Bash(curl -H 'Authorization: Bearer {SECRETS[3]}' x)",
                              f"Bash(curl -H 'X-Api-Key: {SECRETS[6]}' x)"], "defaultMode": "default"},
    "hooks": {
        "PostToolUse": [{"matcher": "Edit|Write", "hooks": [
            {"type": "command", "command": "python ~/.claude/hooks/fmt.py", "timeout": 30},
            {"type": "command", "command": OTHER_HOOK, "args": [SECRET], "if": "Bash(x)"},
            {"type": "command", "command": URL_HOOK},
            {"type": "command", "command": ENV_HOOK},
            {"type": "command", "command": XKEY_HOOK},
            {"type": "command", "command": TOKEN_ENV_HOOK},
            {"type": "command", "command": KV_HOOK}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python ~/.claude/hooks/guard.py"}]}]},
    "zeta": 1, "alpha": {"nested": [1, 2, {"x": None}]},
}


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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

    def run_edit(self, *args, file=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = settings_edit.main([str(file or self.file), *map(str, args)])
            except SystemExit as exc:
                code = exc.code
        for secret in SECRETS:
            self.assertNotIn(secret, out.getvalue() + err.getvalue(), "a secret from the file was printed")
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

    def test_add_hook_prints_only_the_program_and_the_script_name_but_writes_the_command_as_given(self):
        command = f"python ~/.claude/hooks/h.py --api-key {SECRET}"
        code, out, err = self.run_edit("add-hook", "--event", "Stop", "--command", command)
        self.assertEqual(code, 0, err)
        self.assertIn('"command": "python h.py …"', out)
        self.assertNotIn("--api-key", out)
        self.assertNotIn(".claude", out)
        self.assertEqual(self.data()["hooks"]["Stop"][0]["hooks"][0]["command"], command)

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
        self.assertEqual(len(self.data()["hooks"]["PostToolUse"][0]["hooks"]), 6)

    def test_index_removes_exactly_the_nth_hook_even_when_two_are_identical_and_keeps_the_order_of_the_rest(self):
        same = {"type": "command", "command": "python ~/.claude/hooks/dup.py", "timeout": 5}
        data = json.loads(json.dumps(START))
        data["hooks"]["PostToolUse"] = [
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "a.py"}, dict(same), {"type": "command", "command": "b.py"}]},
            {"matcher": "Write", "hooks": [dict(same), {"type": "command", "command": "c.py"}]}]
        self.write(data)
        code, out, err = self.run_edit("remove-hook", "--event", "PostToolUse", "--index", 3)  # the second identical hook
        self.assertEqual(code, 0, err)
        groups = self.data()["hooks"]["PostToolUse"]
        self.assertEqual([[h["command"] for h in g["hooks"]] for g in groups],
                         [["a.py", "python ~/.claude/hooks/dup.py", "b.py"], ["c.py"]])
        self.assertIn('"matcher": "Write"', out)
        self.write(data)  # now the first of the two identical hooks
        self.assertEqual(self.run_edit("remove-hook", "--event", "PostToolUse", "--index", 1)[0], 0)
        self.assertEqual([[h["command"] for h in g["hooks"]] for g in self.data()["hooks"]["PostToolUse"]],
                         [["a.py", "b.py"], ["python ~/.claude/hooks/dup.py", "c.py"]])
        two_groups = {"hooks": {"Stop": [{"hooks": [dict(same)]}, {"hooks": [dict(same)]}]}}  # identical groups too
        self.write(two_groups)
        self.assertEqual(self.run_edit("remove-hook", "--event", "Stop", "--index", 1)[0], 0)
        self.assertEqual(self.data()["hooks"]["Stop"], [{"hooks": [same]}])

    def test_remove_hook_refuses_zero_or_several_matches_and_lists_masked_candidates_with_an_index(self):
        before = self.file.read_bytes()
        code, _, err = self.run_edit("remove-hook", "--event", "PostToolUse", "--command-contains", "nothing-like-this")
        self.assertEqual(code, 2)
        self.assertIn("no hook command", err)
        self.assertIn("[0] PostToolUse", err)  # zero matches still lists the event's hooks, masked
        self.assertIn("[2] PostToolUse matcher='Edit|Write' command: curl …", err)
        self.assertIn("[5] PostToolUse matcher='Edit|Write' command: python e2.py …", err)  # the TOKEN=x prefix is dropped
        code, _, err = self.run_edit("remove-hook", "--event", "PostToolUse", "--command-contains", "python")
        self.assertEqual(code, 2)
        self.assertIn("pick one with --index", err)
        self.assertIn("[0] PostToolUse matcher='Edit|Write' command: python fmt.py …", err)
        self.assertIn("[1] PostToolUse matcher='Edit|Write' command: python other.py …", err)
        self.assertNotIn("[2]", err)  # the curl hooks do not contain "python"
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.run_edit("remove-hook", "--event", "Stop", "--command-contains", "x")[0], 2)  # no such event

    def test_index_picks_one_of_several_and_must_agree_with_the_text(self):
        code, _, err = self.run_edit("remove-hook", "--event", "PostToolUse", "--index", 1)
        self.assertEqual(code, 0, err)
        commands = [h["command"] for h in self.data()["hooks"]["PostToolUse"][0]["hooks"]]
        self.assertEqual((len(commands), "other.py" in " ".join(commands)), (6, False))
        before = self.file.read_bytes()
        self.assertEqual(self.run_edit("remove-hook", "--event", "PostToolUse", "--index", 0, "--command-contains", "env.py")[0], 2)
        self.assertEqual(self.run_edit("remove-hook", "--event", "PostToolUse", "--index", 99)[0], 2)
        self.assertEqual(self.run_edit("remove-hook", "--event", "PostToolUse")[0], 2)
        self.assertEqual(self.file.read_bytes(), before)

    def test_set_hook_option_prints_only_the_changed_fields_and_never_the_command(self):
        base = ("set-hook-option", "--event", "PreToolUse", "--command-contains", "guard.py")
        code, out, err = self.run_edit(*base, "--on-failure", "block", "--timeout", 9)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.data()["hooks"]["PreToolUse"][0]["hooks"][0],
                         {"type": "command", "command": "python ~/.claude/hooks/guard.py", "onFailure": "block", "timeout": 9})
        before, after = out.split("before:")[1].split("after:")
        self.assertIn('"onFailure": null', before)
        self.assertIn('"onFailure": "block"', after)
        self.assertIn('"timeout": 9', after)
        self.assertNotIn("guard.py", out)
        self.assertNotIn("command", before + after)
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
        self.assertEqual(self.data()["permissions"]["allow"][0], "Bash(make test)")
        self.assertIn("before: (absent)", out)
        before = self.file.read_bytes()
        self.assertIn("nothing to change", self.run_edit(*args)[1])
        self.assertEqual(self.file.read_bytes(), before)
        code, out, _ = self.run_edit("add-permission", "--kind", "allow", "--rule", "Read")
        self.assertEqual(self.data()["permissions"]["allow"][-1], "Read")
        self.assertIn('"Bash(curl -H \u2026)"', out)  # the existing rules that embed a credential keep the tool and two words
        self.assertIn('"Bash(make test)"', out)  # a short plain rule is shown whole
        self.assertNotIn("Authorization", out)

    def test_remove_permission_removes_the_rule_and_is_quiet_when_it_is_absent(self):
        self.assertEqual(self.run_edit("remove-permission", "--kind", "allow", "--rule", "Bash(make test)")[0], 0)
        self.assertNotIn("Bash(make test)", self.data()["permissions"]["allow"])
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
        for text in ("API_KEY", "other.py", "zeta", "alpha", "nested", "example.com", "Authorization", "X-Api"):
            self.assertNotIn(text, out)

    def test_a_secret_never_prints_in_any_operation_dry_run_or_refusal(self):
        runs = [("add-hook", "--event", "PostToolUse", "--matcher", "Edit|Write", "--command", ENV_HOOK + " --extra"),
                ("add-hook", "--event", "PostToolUse", "--command", XKEY_HOOK),
                ("add-hook", "--event", "Stop", "--command", TOKEN_ENV_HOOK),
                ("remove-hook", "--event", "PostToolUse", "--command-contains", "env.py"),
                ("remove-hook", "--event", "PostToolUse", "--command-contains", "python"),
                ("remove-hook", "--event", "PostToolUse", "--command-contains", "nothing-matches-this"),
                ("remove-hook", "--event", "PostToolUse", "--command-contains", "example.com"),
                ("remove-hook", "--event", "PostToolUse", "--index", 1),
                ("remove-hook", "--event", "PostToolUse", "--index", 2),
                ("remove-hook", "--event", "PostToolUse", "--index", 4),
                ("remove-hook", "--event", "PostToolUse", "--index", 5),
                ("remove-hook", "--event", "PostToolUse", "--index", 6),
                ("remove-hook", "--event", "PostToolUse", "--index", 70),
                ("set-hook-option", "--event", "PostToolUse", "--command-contains", "other.py", "--on-failure", "block"),
                ("set-hook-option", "--event", "PostToolUse", "--command-contains", "python", "--on-failure", "block"),
                ("set-hook-option", "--event", "PostToolUse", "--index", 2, "--timeout", 5),
                ("set-hook-option", "--event", "PostToolUse", "--index", 4, "--timeout", 5),
                ("set-hook-option", "--event", "PostToolUse", "--index", 5, "--on-failure", "block"),
                ("set-hook-option", "--event", "PostToolUse", "--index", 6, "--timeout", 5),
                ("add-permission", "--kind", "allow", "--rule", START["permissions"]["allow"][2]),
                ("remove-permission", "--kind", "allow", "--rule", START["permissions"]["allow"][2]),
                ("add-permission", "--kind", "allow", "--rule", "Read"),
                ("remove-permission", "--kind", "allow", "--rule", START["permissions"]["allow"][1]),
                ("set", "--key", "model", "--value", "haiku")]
        for run in runs:
            for extra in ((), ("--dry-run",)):
                code, out, err = self.run_edit(*run, *extra)  # run_edit fails on any printed secret
                self.assertIn(code, (0, 2), (run, err))
                self.write(START)

    def test_indent_crlf_bom_and_a_missing_final_newline_are_kept(self):
        text = json.dumps(START, indent=4).replace("\n", "\r\n")
        self.file.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        self.assertEqual(self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")[0], 0)
        raw = self.file.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n    \"model\"", raw)
        self.assertNotIn(b"\n  \"", raw.replace(b"\r\n", b"\n").replace(b"\n    ", b""))
        self.assertFalse(raw.endswith(b"\n"))
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8-sig"))["permissions"]["ask"], ["Read"])

    def test_a_non_ascii_value_is_written_as_text_not_escapes(self):
        self.write({**START, "note": "caf\u00e9"})
        self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertIn("caf\u00e9", self.file.read_text(encoding="utf-8"))

    # -- the preview is bound to the write

    def test_dry_run_prints_the_change_the_target_and_the_hash_and_writes_nothing(self):
        before = self.file.read_bytes()
        code, out, _ = self.run_edit("add-hook", "--event", "Stop", "--command", "x.py", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("after:", out)
        self.assertIn("dry run: nothing written", out)
        self.assertIn(f"sha256: {hashlib.sha256(before).hexdigest()}", out)
        self.assertIn(f"target: {self.file}", out)
        self.assertEqual(self.file.read_bytes(), before)

    def test_expect_sha256_lets_the_previewed_file_through_and_refuses_a_changed_one(self):
        digest = sha(self.file)
        code, out, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", "--expect-sha256", digest.upper())
        self.assertEqual(code, 0, err)
        self.assertIn(f"new sha256: {sha(self.file)}", out)
        before = self.file.read_bytes()
        code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Edit", "--expect-sha256", digest)
        self.assertEqual(code, 2)
        self.assertIn("changed since the preview", err)
        self.assertEqual(self.file.read_bytes(), before)

    def test_a_file_that_changes_between_reading_and_writing_is_not_overwritten(self):
        real = settings_edit.Document.render

        def racing(doc):
            self.file.write_text('{"someone": "else"}', encoding="utf-8")
            return real(doc)

        with mock.patch.object(settings_edit.Document, "render", racing):
            code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertEqual(code, 2)
        self.assertIn("changed while", err)
        self.assertEqual(self.data(), {"someone": "else"})

    # -- refusals

    def test_a_file_that_is_not_valid_json_is_exit_2_without_echoing_it_or_changing_it(self):
        self.file.write_text('{"env": {"k": "%s"}, oops' % SECRET, encoding="utf-8")
        before = self.file.read_bytes()
        code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)
        self.assertEqual(self.file.read_bytes(), before)

    def test_a_file_that_could_not_be_written_back_faithfully_is_refused_not_rewritten(self):
        for label, text in (("a repeated key", '{"a": 1, "hooks": {}, "a": 2, "env": {"k": "%s"}}' % SECRET),
                            ("a repeated key deeper down", '{"x": {"k": 1, "k": 2}, "env": "%s"}' % SECRET),
                            ("1e400", '{"big": 1e400, "env": "%s"}' % SECRET),
                            ("-1e400", '{"big": -1e400}'),
                            ("a tiny number that becomes zero", '{"tiny": 1e-400}'),
                            ("NaN", '{"n": NaN}'),
                            ("Infinity", '{"n": Infinity}'),
                            ("-Infinity", '{"n": -Infinity}')):
            self.file.write_text(text, encoding="utf-8")
            before = self.file.read_bytes()
            code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")
            self.assertEqual(code, 2, label)
            self.assertIn("cannot be rewritten", err, label)
            self.assertEqual(self.file.read_bytes(), before, label)
        self.file.write_text('{"small": 1.5e-7, "zero": 0.0, "n": 12345678901234567890}', encoding="utf-8")
        self.assertEqual(self.run_edit("add-permission", "--kind", "ask", "--rule", "Read")[0], 0)  # in range: fine

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
        code, out, _ = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", "--create", "--dry-run", file=missing)
        self.assertEqual((code, "sha256: absent" in out), (0, True))
        self.assertFalse(missing.exists())
        self.assertEqual(self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", "--create", "--expect-sha256", "absent", file=missing)[0], 0)
        self.assertEqual(json.loads(missing.read_text(encoding="utf-8")), {"permissions": {"ask": ["Read"]}})

    def test_a_folder_is_refused(self):
        self.assertEqual(self.run_edit("set", "--key", "model", "--value", "x", file=self.base)[0], 2)

    # -- links

    def make_link(self, link: pathlib.Path, target: pathlib.Path):
        try:
            os.symlink(target, link, target_is_directory=target.is_dir())
        except (OSError, NotImplementedError):
            self.skipTest("this system will not create symlinks for the test")

    def test_a_path_through_a_linked_folder_or_file_is_refused_unless_follow_links_and_shows_the_target(self):
        real_dir = self.base / "real"
        real_dir.mkdir()
        (real_dir / "settings.json").write_bytes(self.file.read_bytes())
        self.make_link(self.base / "linked", real_dir)
        via_dir = self.base / "linked" / "settings.json"
        before = (real_dir / "settings.json").read_bytes()
        code, _, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", file=via_dir)
        self.assertEqual(code, 2)
        self.assertIn("--follow-links", err)
        self.assertEqual((real_dir / "settings.json").read_bytes(), before)
        code, out, err = self.run_edit("add-permission", "--kind", "ask", "--rule", "Read", "--follow-links", file=via_dir)
        self.assertEqual(code, 0, err)
        self.assertIn(f"target: {real_dir / 'settings.json'}", out)
        self.assertIn("Read", json.loads((real_dir / "settings.json").read_text(encoding="utf-8"))["permissions"]["ask"])
        self.make_link(self.base / "file-link.json", real_dir / "settings.json")
        self.assertEqual(self.run_edit("set", "--key", "model", "--value", "x", file=self.base / "file-link.json")[0], 2)

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


class MaskTest(unittest.TestCase):
    """The one masking rule: the program name and the base name of the first path-like argument, then an ellipsis."""

    def test_only_the_program_and_the_first_script_name_survive(self):
        cases = {
            "python ~/.claude/hooks/guard_main.py": "python guard_main.py \u2026",
            "python ~/.claude/hooks/g.py --mode strict --timeout 5": "python g.py \u2026",
            "C:\\Users\\me\\.claude\\hooks\\x.py": "x.py \u2026",
            "/usr/bin/python3 /opt/h/run.py a b": "python3 run.py \u2026",
            "python g.py --token abc123": "python g.py \u2026",
            "python g.py --api-key=abc123": "python g.py \u2026",
            "API_KEY=abc123 python g.py": "python g.py \u2026",
            "TOKEN=x cmd": "cmd \u2026",
            "A=1 B='two words' python g.py": "python g.py \u2026",
            "PASSWORD='p w' python g.py": "python g.py \u2026",
            "curl -H 'Authorization: Bearer abc.def' x": "curl \u2026",
            "curl -H \"X-Api-Key: abc/def.py\" https://u:p@h/x": "curl \u2026",
            "curl https://user:pw@example.com/p/secret.sh": "curl \u2026",
            "python g.py dGhpcyBpcyBhIHNlY3JldA==": "python g.py \u2026",
            "": "\u2026",
            "TOKEN=only": "\u2026",
            "python -c 'open(\"/etc/x\")'": "python \u2026",
        }
        for raw, expected in cases.items():
            self.assertEqual(measure.mask_command(raw), expected, raw)
        self.assertEqual(measure.mask_command(None), "\u2026")

    def test_an_unbalanced_quote_still_hides_the_rest(self):
        self.assertEqual(measure.mask_command("python g.py 'unterminated secret"), "python g.py \u2026")

    def test_a_permission_rule_keeps_its_tool_name_and_masks_the_inside(self):
        cases = {"Read": "Read", "mcp__srv__tool": "mcp__srv__tool", "TOKEN=x Bash": "Bash \u2026",
                 # shown verbatim: short, and none of = @ quotes :// a header or a long token
                 "Bash(git push:*)": "Bash(git push:*)", "Bash(npm run test:*)": "Bash(npm run test:*)",
                 "Read(./.env)": "Read(./.env)", "Edit(src/**)": "Edit(src/**)", "Bash(git push origin main)": "Bash(git push origin main)",
                 "Bash(*)": "Bash(*)",
                 # masked: the tool and the first two words (a word with a secret shape ends the list), then an ellipsis
                 'Bash(curl -H "Authorization: Bearer x" *)': "Bash(curl -H \u2026)",
                 "Bash(curl -H 'X-Api-Key: k' x)": "Bash(curl -H \u2026)",
                 "Bash(TOKEN=abc curl x)": "Bash(\u2026)", "Bash(curl https://u:p@h/x)": "Bash(curl \u2026)",
                 "Bash(curl X-Api-Key: k)": "Bash(curl \u2026)", "Bash(a --k=v)": "Bash(a \u2026)",
                 "Read(" + "a" * 30 + ")": "Read(\u2026)", "Bash(" + "git status " * 7 + ")": "Bash(git status \u2026)",
                 "Bash(" + "x" * 61 + ")": "Bash(\u2026)"}
        for raw, expected in cases.items():
            self.assertEqual(measure.mask_rule(raw), expected, raw)
        self.assertIs(settings_edit.mask_command, measure.mask_command)  # one rule, not a copy
        self.assertIs(settings_edit.mask_rule, measure.mask_rule)

    def test_a_secret_in_every_form_stays_out_of_every_operations_output(self):
        # the planted forms: quoted X-Api-Key header, Bearer, URL userinfo, key=value, env-prefixed TOKEN=x
        for command in (XKEY_HOOK, URL_HOOK, KV_HOOK, TOKEN_ENV_HOOK, ENV_HOOK, OTHER_HOOK):
            shown = measure.mask_command(command)
            for secret in SECRETS:
                self.assertNotIn(secret, shown, command)


if __name__ == "__main__":
    unittest.main()
