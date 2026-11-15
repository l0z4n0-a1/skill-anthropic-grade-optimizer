"""Tests for the deterministic half: measurement, the quote gate, and knowledge-base queries.

Each test builds a small setup or knowledge base in a temporary directory, so the
suite never reads the developer's own ~/.claude. Run: python -m unittest discover tests
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import kb_gate  # noqa: E402
import measure  # noqa: E402


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_setup(base: pathlib.Path):
    """A user directory and a project with one of each kind of piece, plus one session."""
    home, project = base / "home" / ".claude", base / "proj"
    write(home / "CLAUDE.md", "# Global\n" + "word " * 400 + "\n@notes/extra.md\n")
    write(home / "notes" / "extra.md", "imported " * 100)
    write(home / "skills" / "deploy" / "SKILL.md",
          "---\nname: deploy\ndescription: Deploys the service to staging and production environments safely\n---\n" + "step\n" * 50)
    write(home / "skills" / "deploy" / "run.sh", "echo hi")
    write(home / "skills" / "manual" / "SKILL.md",
          "---\nname: manual\ndescription: Only typed by the person\ndisable-model-invocation: true\n---\nbody\n")
    write(home / "skills" / "release" / "SKILL.md",
          "---\nname: release\ndescription: Releases the service to staging and production environments with checks\n---\nbody\n")
    write(home / "agents" / "reviewer.md",
          "---\nname: reviewer\ndescription: Reviews a diff for correctness problems\nmodel: sonnet\ntools: Read, Grep\n---\nYou review.\n")
    write(home / "agents" / "idle.md", "---\nname: idle\ndescription: Never spawned by anything at all\n"
          "tools:\n  - \"Read\"\n  - \"Grep\"\nmcpServers:\n  vault:\n    env:\n      API_KEY: frontmatter-secret\n---\nIdle.\n")
    write(home / "skills" / "muted" / "SKILL.md", "---\nname: muted\ndescription: Turned off in settings by the owner\n---\nbody\n")
    write(home / "skills" / "short" / "SKILL.md", "---\nname: short\ndescription: Listed by name only, description hidden\n---\nbody\n")
    write(home / "rules" / "always.md", "Always applies.\n")
    write(home / "rules" / "scoped.md", "---\npaths: src/**\n---\nOnly for src.\n")
    write(home / "settings.json", json.dumps({
        "env": {"SECRET_TOKEN": "do-not-leak"}, "autoCompactWindow": 300000,
        "skillOverrides": {"muted": "off", "short": "name-only"},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python ~/.claude/hooks/missing_guard.py", "timeout": 5, "onFailure": "block"}]}]}}))
    write(project / "CLAUDE.md", "# Project\nline\n")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    use = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 890, "output_tokens": 50}
    rows = [
        {"type": "user", "timestamp": now, "message": {"role": "user", "content": "<command-name>/manual</command-name>"}},
        # the same assistant message arrives on two lines; its usage must be counted once
        {"type": "assistant", "timestamp": now, "effort": "medium", "message": {"id": "m1", "model": "claude-opus-5-5", "usage": use, "content": [
            {"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "deploy"}}]}},
        {"type": "assistant", "timestamp": now, "effort": "medium", "message": {"id": "m1", "model": "claude-opus-5-5", "usage": use, "content": [
            {"type": "tool_use", "id": "t2", "name": "Agent", "input": {"subagent_type": "reviewer", "prompt": "x"}}]}},
        {"type": "user", "timestamp": now, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "abcde"}, {"type": "image", "source": {"data": "x" * 999}}]}]}},
    ]
    write(home / "projects" / "p1" / "s1.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
    # a resumed session copies earlier messages into a new file: m1 must still count once
    old = {"type": "user", "timestamp": "2020-01-01T00:00:00.000Z", "message": {"role": "user", "content": "<command-name>/release</command-name>"}}
    write(home / "projects" / "p1" / "s2.jsonl", json.dumps(rows[1]) + "\n" + json.dumps(old) + "\nnot json with \"usage\" in it\n")
    sub = {"type": "assistant", "timestamp": now, "message": {"id": "m9", "model": "claude-haiku-5-5", "content": [],
                                                              "usage": {"input_tokens": 1, "output_tokens": 150}}}
    write(home / "projects" / "p1" / "s1" / "subagents" / "a1.jsonl", json.dumps(sub) + "\n")
    return home, project


class MeasureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home, cls.project = make_setup(pathlib.Path(cls.tmp.name))
        cls.doc = measure.build(cls.home, cls.project, 30)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_instruction_files_follow_imports(self):
        names = {pathlib.Path(f["path"]).name: f for f in self.doc["instruction_files"]}
        self.assertIn("extra.md", names)
        self.assertTrue(names["extra.md"]["imported_by"].endswith("CLAUDE.md"))
        inside = [f for f in self.doc["instruction_files"] if f["path"].startswith(self.tmp.name)]
        self.assertEqual(len(inside), 3)  # user file, its import, project file

    def test_hidden_skill_costs_nothing_at_session_start(self):
        skills = {s["name"]: s for s in self.doc["skills"]}
        self.assertEqual(skills["manual"]["always_est_tokens"], 0)
        self.assertGreater(skills["deploy"]["always_est_tokens"], 0)
        self.assertEqual(skills["deploy"]["bundled_files"], 1)

    def test_path_scoped_rule_is_not_fixed_context(self):
        loads = {r["name"]: r["loads"] for r in self.doc["rules"]}
        self.assertEqual(loads["always"], "session start")
        self.assertEqual(loads["scoped"], "when a matching file is read")
        fixed = self.doc["fixed_context_est_tokens"]
        self.assertEqual(fixed["total"], sum(v for k, v in fixed.items() if k != "total"))

    def test_settings_keep_names_and_drop_values(self):
        dumped = json.dumps(self.doc)
        self.assertNotIn("do-not-leak", dumped)
        self.assertEqual(self.doc["settings"]["files"][0]["env_names"], ["SECRET_TOKEN"])

    def test_hook_with_missing_script_is_reported(self):
        hook = self.doc["settings"]["hooks"][0]
        self.assertEqual(hook["event"], "PreToolUse")
        self.assertEqual(len(hook["scripts_missing"]), 1)

    def test_usage_counts_each_message_once(self):
        use = self.doc["usage"]
        self.assertEqual(use["tokens_by_scope_and_model"]["main | claude-opus-5-5"]["output"], 50)
        self.assertEqual(use["tokens_by_scope_and_model"]["main | claude-opus-5-5"]["requests"], 1)
        self.assertEqual(use["skill_invocations"], {"deploy": 1})
        self.assertEqual(use["agent_spawns"], {"reviewer": 1})
        self.assertEqual(use["cache_read_share_of_prompt_tokens"], 0.8891)  # 890 of 1,001 prompt-side tokens
        self.assertEqual(use["subagent_share_of_output_tokens"], 0.75)

    def test_tool_result_size_ignores_images(self):
        self.assertEqual(self.doc["usage"]["tool_result_chars"], {"Agent": 5})

    def test_never_invoked_counts_typed_commands_as_use(self):
        never = self.doc["never_invoked_in_window"]
        # deploy was invoked; manual and muted are not model-invocable; /release was typed outside the window
        self.assertEqual(never["skills"], ["release", "short"])
        self.assertEqual(never["agents"], ["idle"])

    def test_overlapping_descriptions_are_listed(self):
        pairs = {(p["a"], p["b"]) for p in self.doc["description_overlaps"]}
        self.assertIn(("skill:deploy", "skill:release"), pairs)

    def test_compare_reports_a_change(self):
        after = json.loads(json.dumps(self.doc))
        after["fixed_context_est_tokens"]["total"] -= 100
        self.assertIn("fixed context: total", measure.compare(self.doc, after))
        self.assertIn("no measured difference", measure.compare(self.doc, self.doc))


class HardeningTest(unittest.TestCase):
    """Defects found by independent review; each stays fixed only while its test exists."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home, cls.project = make_setup(pathlib.Path(cls.tmp.name))
        cls.doc = measure.build(cls.home, cls.project, 30)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_unknown_frontmatter_blocks_are_named_not_copied(self):
        idle = next(a for a in self.doc["agents"] if a["name"] == "idle")
        self.assertNotIn("frontmatter-secret", json.dumps(self.doc))
        self.assertIn("mcpServers", idle["other_fields"])
        self.assertEqual(idle["tools"], "Read, Grep")

    def test_skill_overrides_change_listing_cost(self):
        skills = {s["name"]: s for s in self.doc["skills"]}
        self.assertEqual((skills["muted"]["visibility"], skills["muted"]["always_est_tokens"]), ("off", 0))
        self.assertFalse(skills["muted"]["model_invocable"])
        self.assertEqual(skills["short"]["visibility"], "name-only")
        self.assertEqual(skills["short"]["always_est_tokens"], measure.est_tokens(len("short")))

    def test_hook_options_and_safe_settings_values_are_kept(self):
        self.assertEqual(self.doc["settings"]["hooks"][0]["options"], {"onFailure": "block"})
        self.assertEqual(self.doc["settings"]["files"][0]["values"], {"autoCompactWindow": 300000})

    def test_repeated_message_ids_and_bad_lines(self):
        use = self.doc["usage"]
        self.assertEqual(use["tokens_by_scope_and_model"]["main | claude-opus-5-5"]["requests"], 1)
        self.assertEqual(use["avg_prompt_tokens_per_request"], {"main": 1000, "subagent": 1})
        self.assertTrue(any("not valid JSON" in u for u in self.doc["unreadable"]))

    def test_wrong_shaped_json_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(home / "settings.json", "[]")
            write(project / ".claude" / "settings.json", json.dumps({"enabledPlugins": ["x"], "hooks": {"PreToolUse": "oops"}, "env": 3}))
            write(project / ".mcp.json", json.dumps({"mcpServers": ["a", "b"]}))
            write(home / "plugins" / "installed_plugins.json", "null")
            row = {"type": "assistant", "timestamp": "2999-01-01T00:00:00", "message": {
                "id": "x", "usage": {"output_tokens": 1},
                "content": ["str", {"type": "tool_use", "id": "t", "name": "Agent", "input": "str"}]}}
            write(home / "projects" / "p" / "s.jsonl", json.dumps(row) + "\n")
            doc = measure.build(home, project, 30)
            self.assertEqual(doc["usage"]["agent_spawns"], {"(unspecified)": 1})
            self.assertEqual(doc["usage"]["typed_agent_share_of_spawns"], 0.0)
            self.assertTrue(any("expected a JSON object" in u for u in doc["unreadable"]))

    def test_agents_md_is_not_fixed_context_when_claude_md_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(home / "CLAUDE.md", "u")
            write(project / "CLAUDE.md", "p" * 40)
            write(project / "AGENTS.md", "a" * 4000)
            doc = measure.build(home, project, 0)
            agents_md = next(f for f in doc["instruction_files"] if f["path"].endswith("AGENTS.md") and f["path"].startswith(tmp))
            self.assertEqual(agents_md["loads"], "only if no CLAUDE.md is found")
            self.assertLess(doc["fixed_context_est_tokens"]["instruction_files"], 1000)


class GateTest(unittest.TestCase):
    """The gate is only a gate if it can fail: each bad claim below must be rejected."""

    def run_gate(self, claim: dict, snapshot: str = "The cap is 1,536 characters in the skill listing, per the docs."):
        with tempfile.TemporaryDirectory() as tmp:
            kb = pathlib.Path(tmp)
            write(kb / "sources.json", json.dumps([{"id": "src", "url": "https://example.com/doc.md"}]))
            if snapshot is not None:
                write(kb / "snapshots" / "src.md", snapshot)
            write(kb / "claims" / "c.jsonl", json.dumps(claim) + "\n")
            old_kb, old_argv = kb_gate.KB, sys.argv
            kb_gate.KB, sys.argv = kb, ["kb_gate.py", "--json"]
            try:
                import contextlib
                import io
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = kb_gate.main()
            finally:
                kb_gate.KB, sys.argv = old_kb, old_argv
            return code, json.loads(buf.getvalue())

    GOOD = {"id": "skills-001", "topic": "skills", "kind": "fact", "applies_to": ["claude-code"], "claim": "c",
            "why": "w", "check": "k", "quote": "The cap is 1,536 characters in the skill listing", "source": "src"}

    def test_verbatim_quote_passes(self):
        code, report = self.run_gate(self.GOOD)
        self.assertEqual((code, report["ok"]["c.jsonl"]), (0, 1))

    def test_whitespace_and_typographic_quotes_are_normalised(self):
        claim = dict(self.GOOD, quote="The  cap is 1,536\ncharacters in the skill listing")
        self.assertEqual(self.run_gate(claim)[0], 0)

    def test_altered_quote_fails(self):
        code, report = self.run_gate(dict(self.GOOD, quote="The cap is 2,000 characters in the skill listing"))
        self.assertEqual(code, 1)
        self.assertIn("quote not in src", report["errors"][0])

    def test_missing_field_and_unknown_source_fail(self):
        self.assertEqual(self.run_gate({k: v for k, v in self.GOOD.items() if k != "why"})[0], 1)
        self.assertEqual(self.run_gate(dict(self.GOOD, source="nope"))[0], 1)

    def test_padding_cannot_stand_in_for_a_quote(self):
        self.assertEqual(self.run_gate(dict(self.GOOD, quote=" " * 30))[0], 1)
        self.assertEqual(self.run_gate(dict(self.GOOD, quote="- " * 20))[0], 1)

    def test_an_empty_knowledge_base_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = pathlib.Path(tmp)
            write(kb / "sources.json", "[]")
            write(kb / "claims" / "c.jsonl", "\n\n")
            old_kb, old_argv = kb_gate.KB, sys.argv
            kb_gate.KB, sys.argv = kb, ["kb_gate.py", "--json"]
            try:
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(kb_gate.main(), 1)
            finally:
                kb_gate.KB, sys.argv = old_kb, old_argv

    def test_missing_snapshot_is_not_a_pass(self):
        code, report = self.run_gate(self.GOOD, snapshot=None)
        self.assertEqual(code, 2)
        self.assertEqual(report["missing_snapshots"], ["src"])


class RepositoryKnowledgeBaseTest(unittest.TestCase):
    def test_every_claim_has_a_unique_id_and_a_known_source(self):
        """Structure only, so it runs without the uncommitted snapshots; quotes are checked by kb_gate.py."""
        sources = {s["id"] for s in json.loads((ROOT / "kb" / "sources.json").read_text(encoding="utf-8"))}
        seen = set()
        for path in sorted((ROOT / "kb" / "claims").glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                claim = json.loads(line)
                self.assertNotIn(claim["id"], seen, f"duplicate id in {path.name}")
                seen.add(claim["id"])
                self.assertIn(claim["source"], sources)
                self.assertIn(claim["topic"], kb_gate.TOPICS)
        self.assertGreater(len(seen), 100)

    def test_query_script_selects_by_topic_and_model(self):
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "kb.py"), "show", "model", "--model", "claude-opus-5-5"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("[claude-haiku-5-5]", out.stdout)
        miss = subprocess.run([sys.executable, str(ROOT / "scripts" / "kb.py"), "cite", "nope-1"], capture_output=True, text=True)
        self.assertEqual(miss.returncode, 1)


if __name__ == "__main__":
    unittest.main()
