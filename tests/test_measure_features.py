"""Tests for the `features` block of scripts/measure.py: what a setup configures, derived from records already read.

Every test builds its own setup under a temporary directory (see tests/test_measure_hardening.py, whose
fixture class is reused). Run: python -m unittest discover -s tests -t .
"""
import json
import unittest

from tests import test_measure_hardening as h

measure = h.measure
write = h.write


class FeaturesTest(h.Isolated):
    def full_setup(self):
        hook = lambda cmd, **kw: {"type": "command", "command": cmd, **kw}  # noqa: E731
        self.settings("user", {
            "outputStyle": "terse", "statusLine": {"type": "command", "command": "echo hi"},
            "enabledPlugins": {"a@m": True, "b@m": False},
            "permissions": {"allow": ["Bash(make test)", "Read"], "ask": ["Bash(git commit*)"], "deny": ["Bash(git push origin main)"]},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [hook("python ~/.claude/hooks/g.py", onFailure="block"), hook("python ~/.claude/hooks/h.py")]}],
                "Stop": [{"hooks": [hook("python ~/.claude/hooks/s.py", onFailure="block")]}],
                "PostToolUse": [{"matcher": "Edit", "hooks": [hook("python ~/.claude/hooks/f.py")]}]}})
        self.settings("project", {"permissions": {"deny": ["Read(./.env)"]}})
        write(self.home / "agents" / "a.md", "---\nname: a\ndescription: x\nmodel: haiku\neffort: low\ntools: Read, Grep\n---\nbody\n")
        write(self.home / "agents" / "b.md", "---\nname: b\ndescription: y\nmodel: opus\n---\nbody\n")
        write(self.home / "agents" / "c.md", "---\nname: c\ndescription: z\n---\nbody\n")
        write(self.home / "skills" / "s1" / "SKILL.md",
              "---\nname: s1\ndescription: d\ndisable-model-invocation: true\nallowed-tools: Read\n---\nbody\n")
        write(self.home / "skills" / "s1" / "scripts" / "run.py", "print(1)\n")
        write(self.home / "skills" / "s2" / "SKILL.md", "---\nname: s2\ndescription: d\nuser-invocable: false\n---\nbody\n")
        write(self.home / "skills" / "s3" / "SKILL.md", "---\nname: s3\ndescription: d\n---\nbody\n")
        write(self.project / ".claude" / "rules" / "api.md", "---\npaths:\n  - src/api/**\n---\nrule\n")
        write(self.project / ".claude" / "rules" / "always.md", "no paths\n")
        write(self.project / ".mcp.json", json.dumps({"mcpServers": {"one": {"command": "x", "args": ["SECRET"]}, "two": {"type": "http", "url": "u"}}}))

    def value(self, doc, key):
        item = doc["features"][key]
        self.assertEqual(set(item), {"value", "not_measured"}, key)
        return item["value"]

    def test_a_configured_setup_is_counted_from_its_records(self):
        self.full_setup()
        doc = self.build()
        self.assertEqual(self.value(doc, "hooks_by_event"), {"PostToolUse": 1, "PreToolUse": 2, "Stop": 1})
        self.assertEqual(self.value(doc, "stop_hooks_exist"), {"Stop": True, "SubagentStop": False})
        self.assertIs(self.value(doc, "pretooluse_hooks_exist"), True)
        self.assertEqual(self.value(doc, "hooks_with_on_failure_block_by_event"), {"PreToolUse": 1, "Stop": 1})
        self.assertEqual(self.value(doc, "permission_rules"), {"allow": 2, "ask": 1, "deny": 2})
        self.assertEqual(self.value(doc, "path_scoped_rules"), 1)
        self.assertEqual(self.value(doc, "agents_frontmatter_fields"), {
            "model": {"set": 2, "not_set": 1}, "effort": {"set": 1, "not_set": 2}, "tools": {"set": 1, "not_set": 2}, "total": 3})
        self.assertEqual(self.value(doc, "skills_frontmatter_flags"), {
            "disable_model_invocation": 1, "user_invocable_false": 1, "allowed_tools_set": 1, "with_bundled_files": 1, "total": 3})
        self.assertEqual(self.value(doc, "mcp_servers"), 2)
        self.assertEqual(self.value(doc, "enabled_plugins"), 1)
        self.assertEqual(self.value(doc, "settings_keys_present"), {"outputStyle": True, "statusLine": True})

    def test_an_empty_setup_shows_zeros_and_says_what_it_cannot_see(self):
        doc = self.build()
        self.assertEqual(self.value(doc, "hooks_by_event"), {})
        self.assertEqual(self.value(doc, "stop_hooks_exist"), {"Stop": False, "SubagentStop": False})
        self.assertIs(self.value(doc, "pretooluse_hooks_exist"), False)
        self.assertEqual(self.value(doc, "permission_rules"), {"allow": 0, "ask": 0, "deny": 0})
        self.assertEqual(self.value(doc, "settings_keys_present"), {"outputStyle": False, "statusLine": False})
        self.assertIn("plugins", doc["features"]["hooks_by_event"]["not_measured"])
        self.assertIn(".claude.json was not read", doc["features"]["mcp_servers"]["not_measured"])
        self.assertIn("any file beside SKILL.md", doc["features"]["skills_frontmatter_flags"]["not_measured"])

    def test_only_key_names_and_counts_are_copied(self):
        self.full_setup()
        text = json.dumps(self.build()["features"])
        for secret in ("SECRET", "echo hi", "terse", "g.py"):
            self.assertNotIn(secret, text)

    def test_compare_works_with_a_baseline_that_has_no_features_and_shows_changes_when_both_have_them(self):
        self.full_setup()
        after = self.build()
        old = {k: v for k, v in self.build().items() if k != "features"}
        text = measure.compare(old, after)
        self.assertNotIn("None", text)
        self.assertNotIn("permission rules", text)
        before = self.build()
        self.settings("user", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x.py"}]}]}})
        changed = self.build()
        text = measure.compare(before, changed)
        self.assertIn("permission rules (deny): 2 -> 1", text)
        self.assertIn("hooks on PreToolUse: 2 -> 0", text)
        self.assertIn("no measured difference", measure.compare(before, before))

    def test_the_cli_writes_the_block_and_compares_against_it(self):
        self.full_setup()
        base = self.base / "base.json"
        code, _, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--out", base)
        self.assertEqual(code, 0, err)
        self.assertIn("features", json.loads(base.read_text(encoding="utf-8")))
        code, out, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--compare", base)
        self.assertEqual((code, "no measured difference" in out), (0, True), err)


if __name__ == "__main__":
    unittest.main()
