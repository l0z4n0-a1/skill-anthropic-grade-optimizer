"""Tests for the deterministic half: measurement, the quote gate, and knowledge-base queries.

Each test builds a small setup or knowledge base in a temporary directory, so the
suite never reads the developer's own ~/.claude. Run: python -m unittest discover tests
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import kb as kb_query  # noqa: E402
import kb_fetch  # noqa: E402
import kb_gate  # noqa: E402
import kb_update  # noqa: E402
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
        self.assertTrue(any("could not be read" in u for u in self.doc["unreadable"]))

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
            self.assertEqual(doc["usage"]["share_of_spawns_to_agents_defined_here"], 0.0)
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
            # an AGENTS.md that a CLAUDE.md imports does load
            write(project / "CLAUDE.md", "see @AGENTS.md")
            doc = measure.build(home, project, 0)
            agents_md = next(f for f in doc["instruction_files"] if f["path"].endswith("AGENTS.md") and f["path"].startswith(tmp))
            self.assertEqual(agents_md["loads"], "session start")

    def test_frontmatter_never_copies_a_block_under_an_unknown_key(self):
        shapes = ['"mcpServers":', "mcpServers :", "# a comment", "servers.mcp:", "'hooks':", "mcpServers:"]
        for shape in shapes:
            text = f"---\nname: x\ndescription: fine\n{shape}\n  vault:\n    env:\n      API_KEY: SECRETQ\n---\nbody\n"
            meta, other, _ = measure.frontmatter(text)
            self.assertNotIn("SECRETQ", json.dumps([meta, other]), shape)
            self.assertEqual(meta["description"], "fine", shape)

    def test_settings_copy_only_allowlisted_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(home / "settings.json", json.dumps({
                "permissions": {"defaultMode": "plan", "additionalDirectories": "LEAK1", "allow": ["a", "b"]},
                "modelSettings": {"claude-opus-5-5": {"effortLevel": "high", "apiKeyHelper": "LEAK2"}},
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python ~/.claude/hooks/g.py", "token": "LEAK3", "onFailure": "block"}]}]}}))
            write(home / "hooks" / "g.py", "")
            write(project / "x", "")
            doc = measure.build(home, project, 0)
            dumped = json.dumps(doc)
            for leak in ("LEAK1", "LEAK2", "LEAK3"):
                self.assertNotIn(leak, dumped)
            files, hook = doc["settings"]["files"][0], doc["settings"]["hooks"][0]
            self.assertEqual(files["permissions"], {"defaultMode": "plan", "additionalDirectories": "(str)", "allow": 2})
            self.assertEqual(files["values"]["modelSettings"], {"claude-opus-5-5": {"effortLevel": "high"}})
            self.assertEqual((hook["options"], hook["other_options"]), ({"onFailure": "block"}, ["token"]))
            # `~` in a hook command means the directory that holds the audited --home, not the auditor's own
            self.assertEqual(hook["scripts_missing"], [])

    def test_hook_script_paths_resolve_the_documented_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(project / ".claude" / "hooks" / "fmt.sh", "")
            write(home / "x", "")
            ok = ['"$CLAUDE_PROJECT_DIR"/.claude/hooks/fmt.sh', "${CLAUDE_PROJECT_DIR}/.claude/hooks/fmt.sh", "./.claude/hooks/fmt.sh"]
            for command in ok:
                self.assertEqual(measure.missing_scripts(command, home, project), [], command)
            self.assertEqual(len(measure.missing_scripts("node ./.claude/hooks/gone.cjs", home, project)), 1)
            self.assertEqual(measure.missing_scripts("$OTHER_DIR/hooks/fmt.sh", home, project), [])  # unknown, not missing

    def test_session_rows_are_counted_once_and_odd_values_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(project / "x", "")
            now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            typed = {"type": "user", "uuid": "u1", "sessionId": "s", "timestamp": now,
                     "message": {"role": "user", "content": "<command-name>/go</command-name>"}}
            odd = {"type": "assistant", "uuid": "u2", "sessionId": "s", "timestamp": now, "message": {
                "id": "m", "model": {"not": "a string"}, "usage": {"output_tokens": "12", "input_tokens": 5}, "content": []}}
            no_time = {"type": "user", "uuid": "u3", "message": {"role": "user", "content": "<command-name>/late</command-name>"}}
            for name in ("a.jsonl", "b.jsonl"):  # a resumed session repeats its rows in a second file
                write(home / "projects" / "p" / name, "\n".join(json.dumps(r) for r in (typed, odd, no_time)) + "\n")
            use = measure.build(home, project, 30)["usage"]
            self.assertEqual(use["typed_commands"], {"go": 1})
            self.assertEqual(use["sessions"]["main"], 1)
            self.assertEqual(use["tokens_total"]["output"], 0)  # a string is not a token count
            self.assertEqual(use["tokens_total"]["input"], 5)
            self.assertIn("main | (unreadable name)", use["tokens_by_scope_and_model"])

    def test_agent_runs_and_cache_rebuilds(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(project / "x", "")
            base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)

            def row(i, minutes, model, read, written, uid):
                return {"type": "assistant", "uuid": uid, "sessionId": "s", "effort": "medium",
                        "timestamp": (base + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        "message": {"id": f"m{i}", "model": model, "content": [], "usage": {
                            "input_tokens": 0, "cache_read_input_tokens": read, "cache_creation_input_tokens": written,
                            "output_tokens": 10, "cache_creation": {"ephemeral_1h_input_tokens": written}}}}
            rows = [row(0, 0, "claude-opus-5-5", 0, 100000, "a"),        # first request: a write, not a rebuild
                    row(1, 1, "claude-opus-5-5", 100000, 1000, "b"),     # normal
                    row(2, 90, "claude-opus-5-5", 0, 101000, "c"),       # 89 minutes later: the one-hour cache is gone
                    row(3, 91, "claude-sonnet-5-5", 0, 102000, "d"),     # model switch
                    row(4, 92, "claude-sonnet-5-5", 102000, 500, "e")]   # normal
            write(home / "projects" / "p" / "s.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
            sub = home / "projects" / "p" / "s" / "subagents"
            for n in (1, 2):
                r = row(10 + n, 2, "claude-haiku-5-5", 0, 2000, f"s{n}")
                r["message"]["usage"]["output_tokens"] = 300
                write(sub / f"agent-{n}.jsonl", json.dumps(r) + "\n")
                write(sub / f"agent-{n}.json", json.dumps({"agentType": "scout", "model": "haiku"}))
            use = measure.build(home, project, 30)["usage"]
            causes = use["cache_rebuilds"]["by_cause"]
            self.assertEqual(causes["after a pause longer than the cache lifetime"], {"count": 1, "tokens_rewritten": 101000})
            self.assertEqual(causes["after a model switch"], {"count": 1, "tokens_rewritten": 102000})
            self.assertEqual(len(causes), 2)
            scout = use["agent_runs"]["scout"]
            self.assertEqual((scout["runs"], scout["output_tokens_per_run"], scout["models"]), (2, 300, {"claude-haiku-5-5": 2}))

    def test_one_piece_can_be_measured_without_a_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = write(pathlib.Path(tmp) / "s" / "SKILL.md", "---\nname: s\ndescription: Does one thing well\n---\nbody\n")
            write(skill.parent / "references" / "more.md", "x" * 400)
            write(skill.parent / "references" / "z.md", "x" * 40)
            write(skill.parent / "README.md", "not something the skill's reader is sent to")
            record = measure.piece(skill.parent)
            self.assertEqual(record["bundled"], {"references": {"files": 2, "est_tokens": 110}})
            self.assertEqual((record["name"], record["always_est_tokens"]), ("s", measure.est_tokens(len("Does one thing well"))))
            self.assertNotIn("README.md", json.dumps(record["bundled"]))


class ThirdReviewTest(unittest.TestCase):
    """Edge cases a third independent review found."""

    def test_only_names_survive_under_a_list_field(self):
        cases = {
            "tools:\n  env:\n    API_KEY: SECRET123": "",
            "tools: {api_key: SECRET123}": "(mapping)",
            "skills:\n\tvault:\n\t\tkey: SECRET123": "",
            "tools:\n  - name: x\n    token: SECRET123": "",
        }
        for block, expected in cases.items():
            meta, other, _ = measure.frontmatter(f"---\nname: n\n{block}\n---\nbody")
            self.assertNotIn("SECRET123", json.dumps([meta, other]), block)
            self.assertEqual(meta.get("tools", meta.get("skills")), expected, block)

    def test_yaml_lists_comments_and_stray_lines(self):
        meta, other, _ = measure.frontmatter('---\ntools:\n- Read\n- Grep\nmodel: "sonnet"  # fast\nsk-ant-BARELINE\n---\n')
        self.assertEqual((meta["tools"], meta["model"], other), ("Read, Grep", "sonnet", []))
        meta, _, _ = measure.frontmatter("---\ndescription: Does x.\n  Use when y: always.\n---\n")
        self.assertEqual(meta["description"], "Does x. Use when y: always.")

    def test_hook_paths_with_spaces_and_a_home_not_named_dot_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / "cfg dir", pathlib.Path(tmp) / "sp ace" / "proj"
            write(home / "hooks" / "x.py", "")
            write(project / "x.sh", "")
            self.assertEqual(measure.missing_scripts('bash "$CLAUDE_PROJECT_DIR"/x.sh', home, project), [])
            self.assertEqual(measure.missing_scripts("python ~/.claude/hooks/x.py", home, project), [])
            self.assertEqual(len(measure.missing_scripts("python ~/.claude/hooks/gone.py", home, project)), 1)
            self.assertEqual(measure.missing_scripts('echo "unbalanced', home, project), [])

    def test_settings_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(project / "x", "")
            write(home / "settings.json", json.dumps({
                "skillOverrides": {"a": "off", "b": "SECRET9"},
                "permissions": {"deny": ["Bash(git push origin main)", 7], "allow": ["Read"]}}))
            files = measure.build(home, project, 0)["settings"]["files"][0]
            self.assertEqual(files["skillOverrides"], {"a": "off", "b": "(other)"})
            self.assertEqual(files["permission_rules"], {"deny": ["Bash(git push origin main)"], "allow": ["Read"]})

    def test_history_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, project = pathlib.Path(tmp) / ".claude", pathlib.Path(tmp) / "proj"
            write(project / "x", "")
            base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)

            def row(i, minutes, read, written, stamp=None, out=10):
                when = stamp or (base + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                return {"type": "assistant", "uuid": f"u{i}", "sessionId": "s", "timestamp": when, "message": {
                    "id": f"m{i}", "model": "claude-opus-5-5", "content": [], "usage": {
                        "input_tokens": 0, "cache_read_input_tokens": read, "cache_creation_input_tokens": written,
                        "output_tokens": out, "cache_creation": {"ephemeral_1h_input_tokens": written}}}}
            rows = [row(2, 2, 10000, 20000),             # written out of order: this is the compacted request
                    row(0, 0, 0, 150000), row(1, 1, 150000, 500),
                    row(3, 3, 0, 0, stamp="garbage"), row(4, 4, 0, 0, out=10 ** 400)]
            write(home / "projects" / "p" / "s.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
            sub = home / "projects" / "p" / "s" / "subagents"
            write(sub / "agent-1.jsonl", json.dumps(row(9, 5, 0, 100, out=40)) + "\n")
            write(sub / "agent-1.meta.json", json.dumps({"agentType": "scout"}))
            doc = measure.build(home, project, 30)
            use = doc["usage"]
            self.assertEqual(use["cache_rebuilds"]["by_cause"],
                             {"after the context was compacted or cleared": {"count": 1, "tokens_rewritten": 20000}})
            self.assertEqual(use["main_cache_write_tokens_by_lifetime"], {"long": 170500})
            self.assertEqual(use["tokens_by_scope_and_model"]["main | claude-opus-5-5"]["output"], 30)  # the absurd count is 0
            self.assertEqual(use["agent_runs"]["scout"]["runs"], 1)
            self.assertTrue(any("readable timestamp" in u for u in doc["unreadable"]))

    def test_cite_takes_ids_separated_by_spaces_or_commas(self):
        script = [sys.executable, str(ROOT / "scripts" / "kb.py"), "cite"]
        for ids in (["hooks-001", "hooks-005"], ["hooks-001,hooks-005"]):
            out = subprocess.run(script + ids, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("2 claims", out.stdout)
        miss = subprocess.run([sys.executable, str(ROOT / "scripts" / "kb.py"), "show", "nonsense"], capture_output=True, text=True)
        self.assertIn("Topics:", miss.stderr)


class GateTest(unittest.TestCase):
    """The gate is only a gate if it can fail: each bad claim below must be rejected."""

    SNAP = "The cap is 1,536 characters in the skill listing, per the docs."
    SOURCE = {"id": "src", "url": "https://example.com/doc.md", "tier": 1, "topic": "skills"}
    LOCK = {"src": {"sha256": hashlib.sha256(SNAP.encode("utf-8")).hexdigest(), "bytes": 10, "fetched": "2026-11-27",
                  "source": "https://example.com/doc.md"}}

    def run_gate(self, claim, snapshot=SNAP, sources=None, state=None, others=None, only=None):
        """Builds a kb/ in a temp dir and runs main(); `claim` is a dict or a raw line; returns (exit code, parsed --json or None)."""
        with tempfile.TemporaryDirectory() as tmp:
            kb = pathlib.Path(tmp)
            write(kb / "sources.json", json.dumps([self.SOURCE] if sources is None else sources))
            if snapshot is not None:
                write(kb / "snapshots" / "src.md", snapshot)
            write(kb / "claims" / "c.jsonl", (claim if isinstance(claim, str) else json.dumps(claim)) + "\n")
            for name, text in (others or {}).items():
                write(kb / "claims" / name, text)
            for name, text in (state or {}).items():
                write(kb / name, text if isinstance(text, str) else json.dumps(text))
            old_kb, buf = kb_gate.KB, io.StringIO()
            kb_gate.KB = kb
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    code = kb_gate.main(["--json"] + [str(kb / "claims" / n) for n in (only or [])])
            finally:
                kb_gate.KB = old_kb
            return code, (json.loads(buf.getvalue()) if buf.getvalue() else None)

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
        code, report = self.run_gate(dict(self.GOOD, quote="- " * 20))
        self.assertEqual(code, 1)
        self.assertIn(f"at least {kb_gate.MIN_ALNUM_CHARS} letters or digits", report["errors"][0])

    def test_a_number_the_source_does_not_print_is_a_warning(self):
        code, report = self.run_gate(dict(self.GOOD, claim="The listing cap is 1,536 characters, about 3 times the old one."))
        self.assertEqual(code, 0)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("3", report["warnings"][0])
        self.assertNotIn("1,536", report["warnings"][0])
        printed = dict(self.GOOD, claim="The cap is 1536 characters across 2 docs.")
        self.assertEqual(self.run_gate(printed, snapshot="The cap is 1,536 characters in the skill listing, in two docs.")[1]["warnings"], [])
        ranged = dict(self.GOOD, claim="On claude-opus-5-5 a 1,000-1,536 character cap holds.")
        self.assertEqual(self.run_gate(ranged, snapshot="The cap is 1,000 to 1,536 characters in the skill listing.")[1]["warnings"], [])
        part_of_another = dict(self.GOOD, claim="The cap is 536 characters.")
        self.assertEqual(len(self.run_gate(part_of_another)[1]["warnings"]), 1)

    def test_an_empty_knowledge_base_is_not_a_pass(self):
        code, _ = self.run_gate("", sources=[])
        self.assertEqual(code, 1)

    def test_missing_snapshot_is_cannot_check_exit_3_not_a_pass_and_not_misuse(self):
        code, report = self.run_gate(self.GOOD, snapshot=None)
        self.assertEqual(code, 3)
        self.assertEqual(report["missing_snapshots"], ["src"])
        code, _ = self.run_gate(dict(self.GOOD, id="Bad_1"), snapshot=None)
        self.assertEqual(code, 1)  # a wrong claim outranks a missing snapshot

    def test_a_file_argument_that_does_not_exist_is_misuse_exit_2(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(kb_gate.main(["--json", str(ROOT / "no-such-claims.jsonl")]), 2)
        self.assertIn("not a file", err.getvalue())

    def test_malformed_records_are_errors_not_tracebacks(self):
        for raw in ("[1, 2]", "{not json", "42", json.dumps(dict(self.GOOD, applies_to="claude-code"))):
            code, report = self.run_gate(raw)
            self.assertEqual(code, 1, raw)
            self.assertTrue(report["errors"], raw)

    def test_id_shape_and_key_types_are_checked(self):
        for bad_id in ("Skills_1", "skills", "skills-", "-001", "skills-001a"):
            code, report = self.run_gate(dict(self.GOOD, id=bad_id))
            self.assertEqual(code, 1, bad_id)
            self.assertIn("<prefix>-<number>", report["errors"][0])
        self.assertEqual(self.run_gate(dict(self.GOOD, id="multi-part-prefix-012"))[0], 0)
        for key in ("claim", "why", "check", "topic", "source"):
            code, report = self.run_gate(dict(self.GOOD, **{key: ["not", "a", "string"]}))
            self.assertEqual(code, 1, key)

    def test_date_suffixed_model_ids_are_accepted_and_malformed_ones_are_not(self):
        for scope in ("claude-sonnet-4-5-20250929", "claude-haiku-4-5-20251001", "claude-sonnet-4-20250514", "claude-opus-5-5", "claude-opus-5"):
            self.assertEqual(self.run_gate(dict(self.GOOD, applies_to=[scope]))[0], 0, scope)
        for scope in ("claude-sonnet-4-5-2025", "claude-sonnet", "sonnet-4-5", "claude-opus-5-5-fast"):
            self.assertEqual(self.run_gate(dict(self.GOOD, applies_to=[scope]))[0], 1, scope)

    def test_ids_are_unique_across_all_claim_files_even_when_only_some_are_checked(self):
        other = json.dumps(dict(self.GOOD, claim="same id in another file")) + "\n"
        code, report = self.run_gate(self.GOOD, others={"d.jsonl": other}, only=["c.jsonl"])
        self.assertEqual(code, 1)
        self.assertIn("duplicate id skills-001 (also d.jsonl:1)", report["errors"][0])
        code, report = self.run_gate(self.GOOD, others={"d.jsonl": other.replace("skills-001", "skills-002")}, only=["c.jsonl"])
        self.assertEqual(code, 0)

    def test_sources_json_is_validated(self):
        ok = dict(self.SOURCE)
        for label, sources in (("two locators", [dict(ok, bundled="x.md")]),
                               ("no locator", [{k: v for k, v in ok.items() if k != "url"}]),
                               ("duplicate id", [ok, dict(ok)]),
                               ("unsafe id", [dict(ok, id="../x")]),
                               ("tier 4", [dict(ok, tier=4)]),
                               ("tier as text", [dict(ok, tier="1")]),
                               ("no topic", [{k: v for k, v in ok.items() if k != "topic"}]),
                               ("empty locator", [dict(ok, url="")]),
                               ("not an object", ["src"]),
                               ("not a list", {"id": "src"})):
            code, report = self.run_gate(self.GOOD, sources=sources)
            self.assertEqual(code, 1, label)
            self.assertTrue(any("sources.json" in e for e in report["errors"]), label)
        self.assertEqual(self.run_gate(self.GOOD, sources=[{"id": "src", "bundled": "shared/x.md", "tier": 3, "topic": "x"}])[0], 0)

    def test_locks_and_pending_are_validated_when_present(self):
        good = {"snapshots.lock.json": self.LOCK, "index.lock.json": {"https://i.test/llms.txt": ["https://i.test/a.md"]},
                "pending.json": {"sources": {"src": "2026-11-27"}, "new_pages": {"https://i.test/a.md": "2026-11-27"}, "removed_pages": {}}}
        self.assertEqual(self.run_gate(self.GOOD, state=good)[0], 0)
        bad_lock = lambda **kw: {"snapshots.lock.json": {"src": dict(self.LOCK["src"], **kw)}}  # noqa: E731
        for label, state in (("sha", bad_lock(sha256="abc")), ("bytes", bad_lock(bytes="9")), ("date", bad_lock(fetched="27/11/2026")),
                             ("source type", bad_lock(source=5)),
                             ("unknown source", {"snapshots.lock.json": dict(self.LOCK, ghost=self.LOCK["src"])}),
                             ("lock not an object", {"snapshots.lock.json": []}),
                             ("lock not json", {"snapshots.lock.json": "{"}),
                             ("index shape", {"index.lock.json": {"https://i.test/llms.txt": "a.md"}}),
                             ("pending key", {"pending.json": {"things": {}}}),
                             ("pending date", {"pending.json": {"sources": {"src": "yesterday"}}}),
                             ("pending unknown source", {"pending.json": {"sources": {"ghost": "2026-11-27"}}}),
                             ("pending type", {"pending.json": []})):
            code, report = self.run_gate(self.GOOD, state=state)
            self.assertEqual(code, 1, label)

    def test_a_lock_entry_must_name_the_locator_the_source_has_now(self):
        entry = lambda source: {"snapshots.lock.json": {"src": dict(self.LOCK["src"], source=source)}}  # noqa: E731
        code, report = self.run_gate(self.GOOD, state=entry("https://example.com/old.md"))
        self.assertEqual(code, 1)
        self.assertIn("recorded for 'https://example.com/old.md' but sources.json now says 'https://example.com/doc.md'", report["errors"][0])
        bundled = [{"id": "src", "bundled": "shared/x.md", "tier": 1, "topic": "x"}]
        self.assertEqual(self.run_gate(self.GOOD, sources=bundled, state=entry("bundled:shared/x.md"))[0], 0)
        self.assertEqual(self.run_gate(self.GOOD, sources=bundled, state=entry("shared/x.md"))[0], 1)
        local = [{"id": "src", "path": "notes/x.md", "tier": 1, "topic": "x"}]
        self.assertEqual(self.run_gate(self.GOOD, sources=local, state=entry("notes/x.md"))[0], 0)

    def test_a_snapshot_that_differs_from_the_lock_points_to_the_restoring_commands(self):
        code, report = self.run_gate(self.GOOD, state={"snapshots.lock.json": self.LOCK}, snapshot=self.SNAP + " edited")
        self.assertEqual(code, 1)
        self.assertIn("kb_update.py --apply", report["errors"][0])
        self.assertIn("kb_fetch.py --only src", report["errors"][0])


class FetchTest(unittest.TestCase):
    """kb_fetch.py against a temporary kb/ and a dict standing in for the network."""

    A, B, IDX = "https://docs.test/a.md", "https://docs.test/b.md", "https://docs.test/llms.txt"
    REAL_HTTP_GET = staticmethod(kb_fetch.http_get)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.kb = self.root / "kb"
        write(self.kb / "sources.json", json.dumps([{"id": "a", "url": self.A, "tier": 1, "topic": "skills"},
                                                    {"id": "b", "url": self.B, "tier": 1, "topic": "skills"}]))
        self.pages, self.asked, self.deadlines = {self.A: b"a first", self.B: b"b first"}, [], []
        self.patch(kb_fetch, "KB", self.kb)
        self.patch(kb_fetch, "http_get", self.fake_get)
        self.patch(kb_fetch, "today_utc", lambda: "2030-01-02")

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        self.addCleanup(setattr, obj, name, old)
        setattr(obj, name, value)

    def fake_get(self, url, timeout=60, hosts=None, deadline=None):
        self.asked.append(url)
        self.deadlines.append(deadline)
        if url not in self.pages:
            raise urllib.error.URLError(f"no route to {url}")
        return self.pages[url]

    def lock(self, **bodies):
        entries = {sid: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "fetched": "2026-11-01", "source": {"a": self.A, "b": self.B}[sid]}
                   for sid, body in bodies.items()}
        write(self.kb / "snapshots.lock.json", json.dumps(entries))

    def fetch(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kb_fetch.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def pending(self):
        path = self.kb / "pending.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def test_a_changed_source_becomes_pending_and_its_previous_snapshot_is_kept(self):
        self.lock(a=b"a first", b=b"b first")
        write(self.kb / "snapshots" / "a.md", "a first")
        self.pages[self.A] = b"a second"
        code, out, _ = self.fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pending()["sources"], {"a": "2030-01-02"})
        self.assertEqual((self.kb / "snapshots-prev" / "a.md").read_bytes(), b"a first")
        self.assertEqual((self.kb / "snapshots" / "a.md").read_bytes(), b"a second")
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        self.assertEqual((lock["a"]["fetched"], lock["b"]["fetched"]), ("2030-01-02", "2026-11-01"))
        self.assertEqual(lock["a"]["sha256"], hashlib.sha256(b"a second").hexdigest())
        self.pages[self.A] = b"a third"
        self.fetch()
        self.assertEqual((self.kb / "snapshots-prev" / "a.md").read_bytes(), b"a first")  # still the last reviewed one

    def test_a_source_with_no_lock_entry_is_new_and_not_pending(self):
        self.lock(b=b"b first")
        code, _, _ = self.fetch()
        self.assertEqual(code, 0)
        self.assertIsNone(self.pending())
        self.assertEqual((self.kb / "snapshots" / "a.md").read_bytes(), b"a first")

    def test_no_previous_snapshot_is_said_and_a_stale_one_is_removed(self):
        self.lock(a=b"a first", b=b"b first")
        write(self.kb / "snapshots" / "a.md", "tampered, not what the lock recorded")
        write(self.kb / "snapshots-prev" / "a.md", "left over from an older cycle")
        self.pages[self.A] = b"a second"
        _, out, _ = self.fetch("--only", "a")
        self.assertIn("no previous snapshot to diff against for a", out)
        self.assertFalse((self.kb / "snapshots-prev" / "a.md").exists())
        self.assertEqual(self.pending()["sources"], {"a": "2030-01-02"})

    def test_an_unchanged_source_with_a_corrupted_local_snapshot_is_rewritten(self):
        self.lock(a=b"a first", b=b"b first")
        write(self.kb / "snapshots" / "a.md", "corrupted")
        code, out, _ = self.fetch()
        self.assertEqual((code, (self.kb / "snapshots" / "a.md").read_bytes(), self.pending()), (0, b"a first", None))
        self.assertIn("restored=2", out)  # b had no local file at all

    def test_unknown_only_id_is_misuse_before_any_request(self):
        self.assertEqual(self.fetch("--only", "a,zzz")[0], 2)
        self.assertEqual(self.asked, [])

    def test_list_failure_is_actionable_and_exit_1(self):
        code, out, err = self.fetch("--list", "https://docs.test/missing.txt")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("could not read https://docs.test/missing.txt", err)
        self.pages[self.IDX] = b"# index"
        self.assertEqual(self.fetch("--list", self.IDX)[:2], (0, "# index"))

    def test_a_failed_source_is_exit_1_and_the_others_are_still_written(self):
        self.lock(a=b"a first", b=b"b first")
        del self.pages[self.A]
        self.pages[self.B] = b"b second"
        code, out, _ = self.fetch()
        self.assertEqual(code, 1)
        self.assertIn("! a:", out)
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        self.assertEqual((lock["a"]["fetched"], lock["b"]["fetched"]), ("2026-11-01", "2030-01-02"))
        self.assertEqual(set(self.pending()["sources"]), {"b"})

    def test_pending_is_written_before_the_lock(self):
        self.lock(a=b"a first", b=b"b first")
        self.pages[self.A] = b"a second"
        lock_before = (self.kb / "snapshots.lock.json").read_bytes()
        real = kb_fetch.os.replace

        def failing(src, dst, *a, **k):
            if pathlib.Path(dst).name == "snapshots.lock.json":
                raise OSError("disk full")
            return real(src, dst, *a, **k)
        self.patch(kb_fetch.os, "replace", failing)
        with self.assertRaises(OSError):
            self.fetch()
        self.assertEqual((self.kb / "snapshots.lock.json").read_bytes(), lock_before)
        self.assertEqual(list(self.pending()["sources"]), ["a"])
        self.assertEqual([p.name for p in self.kb.rglob("*.tmp")], [])

    def test_a_local_path_source_is_read_relative_to_the_repository_root(self):
        write(self.root / "notes" / "x.md", "local notes")
        self.assertEqual(kb_fetch.read_source({"id": "n", "path": "notes/x.md"}, ""), b"local notes")

    def fake_net(self, chunks, on_read=None, length=None):
        """Replaces the opener http_get builds: it serves `chunks` one per read(), calling on_read() before each.
        `length` is the Content-Length header the response advertises (none by default)."""
        seen = {}

        class Resp:
            def __init__(self):
                self.left = list(chunks)
                self.headers = {} if length is None else {"Content-Length": str(length)}

            def read(self, n=-1):
                if on_read:
                    on_read()
                return self.left.pop(0) if self.left else b""

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class Opener:
            def open(self, req, timeout=None):
                seen["timeout"] = timeout
                return Resp()

        def build(*handlers):
            seen["handlers"] = handlers
            return Opener()
        self.patch(kb_fetch.urllib.request, "build_opener", build)
        return seen

    def test_http_get_refuses_a_response_over_the_byte_cap_and_pins_redirects_to_the_hosts_given(self):
        seen = self.fake_net([b"x" * 11])
        self.patch(kb_fetch, "MAX_BYTES", 10)
        with self.assertRaises(OSError) as cm:
            self.REAL_HTTP_GET("https://docs.test/big.md")
        self.assertIn("larger than 10 bytes", str(cm.exception))
        self.assertEqual((seen["handlers"][0].hosts, seen["timeout"]), ({"docs.test"}, kb_fetch.TIMEOUT))
        seen = self.fake_net([b"x" * 6, b"x" * 4])
        self.assertEqual(self.REAL_HTTP_GET("https://docs.test/ok.md", hosts={"docs.test", "other.test"}), b"x" * 10)
        self.assertEqual(seen["handlers"][0].hosts, {"docs.test", "other.test"})

    def test_http_get_bounds_the_request_and_the_body_by_the_deadline(self):
        clock = [100.0]
        self.patch(kb_fetch, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))

        def slow():
            clock[0] += 2
        seen = self.fake_net([b"abcd", b"efgh", b"ijkl"], on_read=slow)
        with self.assertRaises(TimeoutError) as cm:  # 3 s left: the timeout is cut to 3, and the body is dropped when time runs out
            self.REAL_HTTP_GET("https://docs.test/slow.md", deadline=103.0)
        self.assertIn("while https://docs.test/slow.md was downloading", str(cm.exception))
        self.assertEqual(seen["timeout"], 3.0)
        seen.clear()
        with self.assertRaises(TimeoutError) as cm:  # nothing left: no request is made
            self.REAL_HTTP_GET("https://docs.test/late.md", deadline=clock[0])
        self.assertEqual((seen, "before" in str(cm.exception)), ({}, True))
        clock[0] = 100.0
        self.fake_net([b"abcd"])
        self.assertEqual(self.REAL_HTTP_GET("https://docs.test/fast.md", deadline=1000.0), b"abcd")

    def test_a_source_changing_again_while_pending_never_gets_the_unreviewed_copy_as_previous(self):
        self.lock(a=b"a first", b=b"b first")  # no local snapshots: a fresh clone
        self.pages[self.A] = b"a second"
        self.fetch("--only", "a")
        self.assertFalse((self.kb / "snapshots-prev" / "a.md").exists())
        self.pages[self.A] = b"a third"  # the local file is now "a second", which matches the lock but was never reviewed
        _, out, _ = self.fetch("--only", "a")
        self.assertFalse((self.kb / "snapshots-prev" / "a.md").exists())
        self.assertIn("no previous snapshot to diff against for a", out)

    def test_http_get_rejects_a_body_that_ends_before_its_content_length(self):
        self.fake_net([b"abcd", b"efg"], length=10)
        with self.assertRaises(OSError) as cm:
            self.REAL_HTTP_GET("https://docs.test/cut.md")
        self.assertIn("ended after 7 of 10 bytes", str(cm.exception))
        self.fake_net([b"abcd", b"efghij"], length=10)
        self.assertEqual(self.REAL_HTTP_GET("https://docs.test/whole.md"), b"abcdefghij")
        self.fake_net([b"abc"])  # no length advertised (chunked): nothing to compare with
        self.assertEqual(self.REAL_HTTP_GET("https://docs.test/chunked.md"), b"abc")

    def test_a_cut_download_fails_its_source_and_leaves_the_snapshot_the_lock_and_pending_alone(self):
        self.lock(a=b"a first", b=b"b first")
        write(self.kb / "snapshots" / "a.md", "a first")
        before = (self.kb / "snapshots.lock.json").read_bytes()
        self.patch(kb_fetch, "http_get", self.REAL_HTTP_GET)
        self.fake_net([b"a sec"], length=8)
        code, out, _ = self.fetch("--only", "a")
        self.assertEqual(code, 1)
        self.assertIn("! a:", out)
        self.assertEqual(((self.kb / "snapshots.lock.json").read_bytes(), (self.kb / "snapshots" / "a.md").read_bytes(), self.pending()),
                         (before, b"a first", None))

    def test_the_same_bytes_from_a_new_locator_rewrite_the_lock_entry_and_are_not_pending(self):
        self.lock(a=b"a first", b=b"b first")
        write(self.kb / "snapshots" / "a.md", "a first")
        moved = "https://docs.test/new/a.md"
        write(self.kb / "sources.json", json.dumps([{"id": "a", "url": moved, "tier": 1, "topic": "skills"},
                                                    {"id": "b", "url": self.B, "tier": 1, "topic": "skills"}]))
        self.pages[moved] = b"a first"
        code, out, _ = self.fetch()
        self.assertEqual(code, 0, out)
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        self.assertEqual((lock["a"]["source"], lock["b"]["source"]), (moved, self.B))
        self.assertEqual(lock["a"]["sha256"], hashlib.sha256(b"a first").hexdigest())
        self.assertIn("relocated=1", out)
        self.assertIsNone(self.pending())
        self.assertEqual(self.fetch()[1].split()[:3], ["changed=0", "unchanged=2", "restored=0"])  # and now it is settled

    def test_http_get_reads_one_raw_read_at_a_time_so_the_deadline_is_looked_at_between_them(self):
        class Resp:  # read(n) would wait for n bytes across several socket reads; read1(n) does one
            def __init__(self):
                self.left, self.headers = [b"abc", b"def"], {}

            def read(self, n=-1):
                raise AssertionError("read() waits for a full block")

            def read1(self, n=-1):
                return self.left.pop(0) if self.left else b""

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        opener = types.SimpleNamespace(open=lambda req, timeout=None: Resp())
        self.patch(kb_fetch.urllib.request, "build_opener", lambda *h: opener)
        self.assertEqual(self.REAL_HTTP_GET("https://docs.test/x.md"), b"abcdef")

    def test_the_previous_copy_is_settled_before_pending_is_published(self):
        self.lock(a=b"a second", b=b"b first")  # v2 is the reviewed one; an older cycle left v1 in snapshots-prev
        write(self.kb / "snapshots" / "a.md", "a second")
        write(self.kb / "snapshots-prev" / "a.md", "a first")
        self.pages[self.A] = b"a third"
        real, armed = kb_fetch.os.replace, [True]

        def dying(src, dst, *a, **k):
            if armed[0] and pathlib.Path(dst).parent.name == "snapshots-prev":
                raise OSError("killed")
            return real(src, dst, *a, **k)
        self.patch(kb_fetch.os, "replace", dying)
        with self.assertRaises(OSError):
            self.fetch("--only", "a")
        self.assertIsNone(self.pending())  # not published, so the retry starts a clean cycle
        armed[0] = False
        self.fetch("--only", "a")
        self.assertEqual((self.kb / "snapshots-prev" / "a.md").read_bytes(), b"a second")

    def test_a_redirect_leaves_the_known_hosts_only_with_an_error(self):
        handler = kb_fetch._PinnedRedirect({"docs.test"})
        req = urllib.request.Request("https://docs.test/a")
        for target in ("https://evil.test/x", "http://docs.test/x", "https://docs.test.evil.test/x"):
            with self.assertRaises(urllib.error.URLError) as cm:
                handler.redirect_request(req, None, 302, "Found", {}, target)
            self.assertIn("refused", str(cm.exception), target)
        followed = handler.redirect_request(req, None, 302, "Found", {}, "https://DOCS.test/b")
        self.assertEqual(followed.full_url, "https://DOCS.test/b")


class UpdateTest(unittest.TestCase):
    """kb_update.py against a temporary kb/ and a dict standing in for the network."""

    A, B, C, IDX = "https://docs.test/a.md", "https://docs.test/b.md", "https://docs.test/c.md", "https://docs.test/llms.txt"
    QUOTES = {"a": "the quick brown fox jumps over the lazy dog", "b": "pack my box with five dozen liquor jugs",
              "c": "how vexingly quick daft zebras jump"}
    THREE = b"- [Three](https://docs.test/three.md): z\n"
    REPORT_KEYS = {"schema_version", "lock_oldest", "lock_newest", "changed_sources", "pending", "unchanged", "failed",
                   "not_checked", "not_compared", "new_pages", "removed_pages", "no_index_baseline", "snapshot_mismatch",
                   "unreadable_claim_lines", "incomplete", "compared", "restored_snapshots", "no_previous", "applied", "exit",
                   "relocated"}

    @classmethod
    def page(cls, sid, version="first"):
        """A page that still holds the claims' quote in every version, so the gate keeps passing after a change."""
        return f"page {sid}: {cls.QUOTES[sid]} ({version} version)".encode("utf-8")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name) / "repo"
        self.kb = self.root / "kb"
        (self.root / ".git").mkdir(parents=True)
        write(self.kb / "sources.json", json.dumps([{"id": "a", "url": self.A, "tier": 1, "topic": "skills"},
                                                    {"id": "b", "url": self.B, "tier": 1, "topic": "skills"},
                                                    {"id": "bd", "bundled": "shared/x.md", "tier": 1, "topic": "skills"}]))
        write(self.kb / "claims" / "c.jsonl", "".join(json.dumps({
            "id": cid, "topic": "skills", "kind": "fact", "applies_to": ["all"], "claim": "c", "why": "w", "check": "k",
            "quote": self.QUOTES.get(src, "a quote long enough to pass the gate"), "source": src}) + "\n"
            for cid, src in (("a-1", "a"), ("a-2", "a"), ("b-1", "b"), ("bd-1", "bd"))))
        write(self.kb / "core.json", json.dumps({"q": {"principle": "p", "claims": ["a-1"]}}))
        write(self.kb / "harness.json", json.dumps({"_about": "x"}))
        entry = lambda sid, url, day: {"sha256": hashlib.sha256(self.page(sid)).hexdigest(), "bytes": 1, "fetched": day, "source": url}  # noqa: E731
        write(self.kb / "snapshots.lock.json", json.dumps({"a": entry("a", self.A, "2026-11-01"), "b": entry("b", self.B, "2026-11-10")}))
        write(self.kb / "index.lock.json", json.dumps({self.IDX: ["https://docs.test/one.md", "https://docs.test/two.md"]}))
        self.pages = {self.A: self.page("a"), self.B: self.page("b"), self.C: self.page("c"),
                      self.IDX: b"- [One](https://docs.test/one.md): x\n- [Two](https://docs.test/two.md): y\n"}
        self.asked, self.deadlines = [], []
        self.patch(kb_update, "KB", self.kb)
        self.patch(kb_update, "INDEXES", (self.IDX,))
        self.patch(kb_fetch, "http_get", self.fake_get)
        self.patch(kb_update, "kb_writable", kb_update.kb_writable)

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        self.addCleanup(setattr, obj, name, old)
        setattr(obj, name, value)

    def fake_get(self, url, timeout=60, hosts=None, deadline=None):
        self.asked.append(url)
        self.deadlines.append(deadline)
        if url not in self.pages:
            raise urllib.error.URLError(f"no route to {url}")
        return self.pages[url]

    def tree(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def run_update(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kb_update.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def report(self, *args):
        code, out, _ = self.run_update("--json", *args)
        return code, json.loads(out)

    def pending(self):
        return json.loads((self.kb / "pending.json").read_text(encoding="utf-8"))

    def test_nothing_changed_is_exit_0_and_writes_nothing(self):
        before = self.tree()
        code, report = self.report()
        self.assertEqual(code, 0)
        self.assertEqual((report["unchanged"], report["changed_sources"], report["new_pages"], report["incomplete"]),
                         (["a", "b"], [], [], []))
        self.assertEqual((report["lock_oldest"], report["lock_newest"]), ("2026-11-01", "2026-11-10"))
        self.assertEqual([n["id"] for n in report["not_checked"]], ["bd"])
        self.assertEqual(report["not_compared"], {"sources": 1, "claims": 1})
        self.assertIn("1 bundled or local sources, 1 claims", self.run_update()[1])
        self.assertEqual(self.tree(), before)

    def test_the_json_report_has_a_schema_version_and_exactly_the_documented_keys(self):
        report = self.report()[1]
        self.assertEqual((report["schema_version"], set(report)), (1, self.REPORT_KEYS))
        self.assertEqual(set(self.report("--apply")[1]), self.REPORT_KEYS)

    def test_a_changed_source_is_exit_3_with_its_claims_and_core_ids(self):
        self.pages[self.A] = self.page("a", "second")
        code, report = self.report()
        self.assertEqual(code, 3)
        self.assertEqual(report["changed_sources"], [{"id": "a", "url": self.A, "claims": 2,
                                                      "core_or_harness_ids": ["a-1"], "new": False}])
        self.assertEqual(report["unchanged"], ["b"])
        self.assertIn("2 claims depend on it; in core/harness: a-1", self.run_update()[1])

    def test_new_index_page_is_listed_and_no_baseline_lists_nothing(self):
        self.pages[self.IDX] += self.THREE
        code, report = self.report()
        self.assertEqual(code, 3)
        self.assertEqual(report["new_pages"], [{"index": self.IDX, "url": "https://docs.test/three.md"}])
        (self.kb / "index.lock.json").unlink()
        code, report = self.report()
        self.assertEqual((code, report["new_pages"], report["no_index_baseline"]), (4, [], [self.IDX]))
        self.assertIn("no index baseline", self.run_update()[1])

    def test_a_removed_page_is_work(self):
        self.pages[self.IDX] = b"- [One](https://docs.test/one.md): x\n"
        code, report = self.report()
        self.assertEqual((code, report["removed_pages"]), (3, [{"index": self.IDX, "url": "https://docs.test/two.md"}]))

    def test_a_failed_download_is_listed_and_the_rest_still_run(self):
        del self.pages[self.A]
        code, report = self.report()
        self.assertEqual((code, [f["id"] for f in report["failed"]], report["unchanged"]), (4, ["a"], ["b"]))
        self.assertIn("no route", report["failed"][0]["error"])
        self.assertIn("failed to download", report["incomplete"][0])
        self.pages[self.B] = self.page("b", "second")
        code, report = self.report()
        self.assertEqual((code, [c["id"] for c in report["changed_sources"]]), (3, ["b"]))
        self.pages.clear()
        self.assertEqual(self.run_update()[0], 1)

    def test_the_time_budget_stops_the_downloads_and_reports_the_rest_as_failed(self):
        ticks = iter([0.0] + [10_000.0] * 20)
        self.patch(kb_update, "time", types.SimpleNamespace(monotonic=lambda: next(ticks)))
        code, report = self.report("--max-seconds", "5")
        self.assertEqual((code, self.asked), (1, []))
        self.assertEqual([f["id"] for f in report["failed"]], ["a", "b", self.IDX])
        self.assertIn("time budget of 5 s", report["failed"][0]["error"])

    def test_every_request_gets_the_deadline_of_the_budget(self):
        self.patch(kb_update, "time", types.SimpleNamespace(monotonic=lambda: 50.0))
        self.assertEqual(self.report("--max-seconds", "5")[0], 0)
        self.assertEqual((self.asked, self.deadlines), ([self.A, self.B, self.IDX], [55.0] * 3))

    def test_apply_writes_snapshot_and_locks_and_the_default_mode_does_not(self):
        self.pages[self.A] = self.page("a", "second")
        self.pages[self.IDX] += self.THREE
        before = self.tree()
        self.assertEqual(self.run_update()[0], 3)
        self.assertEqual(self.tree(), before)
        self.patch(kb_fetch, "today_utc", lambda: "2030-01-02")
        code, out, _ = self.run_update("--apply")
        self.assertEqual(code, 3)
        self.assertIn("python scripts/kb_gate.py", out)
        self.assertEqual((self.kb / "snapshots" / "a.md").read_bytes(), self.page("a", "second"))
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["a"]["sha256"], hashlib.sha256(self.page("a", "second")).hexdigest())
        self.assertEqual((lock["a"]["fetched"], lock["b"]["fetched"]), ("2030-01-02", "2026-11-10"))
        index = json.loads((self.kb / "index.lock.json").read_text(encoding="utf-8"))
        self.assertIn("https://docs.test/three.md", index[self.IDX])

    def test_what_apply_downloaded_stays_pending_until_reviewed_and_the_gate_passes(self):
        self.pages[self.A] = self.page("a", "second")
        self.pages[self.IDX] += self.THREE
        self.run_update("--apply")
        code, report = self.report()  # today's bytes now match the lock; the work is still not done
        self.assertEqual((code, report["changed_sources"], report["new_pages"]), (3, [], []))
        self.assertEqual([(p["id"], p["claims"], p["core_or_harness_ids"]) for p in report["pending"]["sources"]],
                         [("a", 2, ["a-1"])])
        self.assertEqual([p["url"] for p in report["pending"]["new_pages"]], ["https://docs.test/three.md"])
        self.assertIn("pending since", self.run_update()[1])
        self.assertEqual(self.run_update("--reviewed", "nope")[0], 2)
        self.assertEqual(self.run_update("--reviewed", "a")[0], 0)
        self.assertEqual(self.report()[0], 3)
        self.assertEqual(self.run_update("--reviewed", " https://docs.test/three.md ")[0], 0)
        self.assertEqual(self.report()[0], 0)
        self.pages[self.B] = self.page("b", "second")
        self.run_update("--apply")
        self.assertEqual(self.report()[0], 3)
        self.assertEqual(self.run_update("--reviewed", "all")[0], 0)
        self.assertEqual(self.report()[0], 0)

    def test_reviewed_refuses_while_the_gate_fails(self):
        self.pages[self.A] = self.page("a", "second")
        self.run_update("--apply")
        claims = (self.kb / "claims" / "c.jsonl").read_text(encoding="utf-8")
        write(self.kb / "claims" / "c.jsonl", claims.replace(self.QUOTES["a"], "a sentence the new page no longer contains"))
        code, _, err = self.run_update("--reviewed", "a")
        self.assertEqual(code, 2)
        self.assertIn("the gate reports", err)
        self.assertIn("kb_gate.py", err)
        self.assertEqual(list(self.pending()["sources"]), ["a"])

    def test_reviewed_looks_at_the_whole_gate_for_errors_but_only_at_the_released_sources_for_snapshots(self):
        self.pages[self.A] = self.page("a", "second")
        self.run_update("--apply")  # the bundled source bd has no snapshot here: the gate cannot check it, and a does not depend on it
        claims = (self.kb / "claims" / "c.jsonl").read_text(encoding="utf-8")
        write(self.kb / "claims" / "c.jsonl", claims.replace(self.QUOTES["b"], "a sentence that source b does not contain"))
        code, _, err = self.run_update("--reviewed", "a")  # an error in an unrelated source still refuses
        self.assertEqual(code, 2)
        self.assertIn("b-1", err)
        write(self.kb / "claims" / "c.jsonl", claims)
        self.assertEqual(self.run_update("--reviewed", "a")[0], 0)

    def test_a_source_changing_again_while_pending_never_gets_the_unreviewed_copy_as_previous(self):
        self.pages[self.A] = self.page("a", "second")
        self.assertEqual(self.report("--apply")[1]["no_previous"], ["a"])  # no local snapshot to keep
        self.pages[self.A] = self.page("a", "third")
        self.assertEqual(self.report("--apply")[1]["no_previous"], ["a"])
        self.assertFalse((self.kb / "snapshots-prev" / "a.md").exists())

    def test_reviewed_refuses_a_source_whose_snapshot_is_missing(self):
        self.pages[self.A] = self.page("a", "second")
        self.run_update("--apply")
        (self.kb / "snapshots" / "a.md").unlink()
        code, _, err = self.run_update("--reviewed", "a")
        self.assertEqual(code, 2)
        self.assertIn("no snapshot for a", err)
        self.assertEqual(list(self.pending()["sources"]), ["a"])

    def test_reviewed_refuses_a_pending_source_without_claims_whose_snapshot_was_edited_here(self):
        n_url = "https://docs.test/n.md"
        sources = json.loads((self.kb / "sources.json").read_text(encoding="utf-8")) + [{"id": "n", "url": n_url, "tier": 1, "topic": "skills"}]
        write(self.kb / "sources.json", json.dumps(sources))
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        lock["n"] = {"sha256": hashlib.sha256(b"n body").hexdigest(), "bytes": 6, "fetched": "2026-11-20", "source": n_url}
        write(self.kb / "snapshots.lock.json", json.dumps(lock))
        write(self.kb / "pending.json", json.dumps({"sources": {"n": "2026-11-20"}}))
        write(self.kb / "snapshots" / "n.md", "n body, edited by hand")  # no claim cites n, so the gate never hashes it
        code, _, err = self.run_update("--reviewed", "n")
        self.assertEqual(code, 2)
        self.assertIn("n does not match snapshots.lock.json", err)
        self.assertEqual(list(self.pending()["sources"]), ["n"])
        write(self.kb / "snapshots" / "n.md", "n body")
        self.assertEqual(self.run_update("--reviewed", "n")[0], 0)
        self.assertEqual(self.pending()["sources"], {})

    def test_reviewed_deletes_the_previous_copy_of_the_source_it_releases(self):
        write(self.kb / "snapshots" / "a.md", self.page("a").decode("utf-8"))
        write(self.kb / "snapshots" / "b.md", self.page("b").decode("utf-8"))
        self.pages[self.A], self.pages[self.B] = self.page("a", "second"), self.page("b", "second")
        self.run_update("--apply")
        self.assertTrue((self.kb / "snapshots-prev" / "a.md").exists() and (self.kb / "snapshots-prev" / "b.md").exists())
        self.assertEqual(self.run_update("--reviewed", "a")[0], 0)
        self.assertFalse((self.kb / "snapshots-prev" / "a.md").exists())
        self.assertTrue((self.kb / "snapshots-prev" / "b.md").exists())  # still pending: its diff is still wanted

    def test_the_same_bytes_from_a_new_locator_are_reported_and_apply_rewrites_the_lock_entry(self):
        moved = "https://docs.test/new/a.md"
        sources = json.loads((self.kb / "sources.json").read_text(encoding="utf-8"))
        sources[0]["url"] = moved
        write(self.kb / "sources.json", json.dumps(sources))
        self.pages[moved] = self.page("a")
        code, report = self.report()
        self.assertEqual((code, report["relocated"], report["changed_sources"]), (4, ["a"], []))
        before = self.tree()
        self.report()
        self.assertEqual(self.tree(), before)  # reporting alone writes nothing
        code, report = self.report("--apply")
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        self.assertEqual((lock["a"]["source"], lock["a"]["sha256"]), (moved, hashlib.sha256(self.page("a")).hexdigest()))
        self.assertFalse((self.kb / "pending.json").exists())
        code, report = self.report()
        self.assertEqual((code, report["relocated"]), (0, []))

    def test_options_that_do_not_go_together_are_misuse_before_any_request(self):
        for args in (["--partial"], ["--reviewed", "a", "--json"], ["--reviewed", "a", "--only", "a"], ["--reviewed", "a", "--out", "x.json"],
                     ["--reviewed", "a", "--bundled-dir", "d"], ["--reviewed", "a", "--partial"], ["--reviewed", "a", "--apply"],
                     ["--reviewed", "a", "--max-seconds", "9"]):
            code, _, err = self.run_update(*args)
            self.assertEqual(code, 2, args)
            self.assertTrue(err, args)
        self.assertEqual(self.asked, [])

    def test_a_selection_that_compares_nothing_is_not_exit_0(self):
        code, out, err = self.run_update("--only", "bd")
        self.assertEqual((code, out, self.asked), (2, "", []))
        self.assertIn("nothing was compared", err)

    def test_apply_keeps_the_last_reviewed_snapshot_while_the_source_is_pending(self):
        write(self.kb / "snapshots" / "a.md", self.page("a").decode())
        self.pages[self.A] = self.page("a", "second")
        code, report = self.report("--apply")
        self.assertEqual(report["no_previous"], [])
        prev = self.kb / "snapshots-prev" / "a.md"
        self.assertEqual(prev.read_bytes(), self.page("a"))
        self.pages[self.A] = self.page("a", "third")
        self.run_update("--apply")
        self.assertEqual((prev.read_bytes(), (self.kb / "snapshots" / "a.md").read_bytes()), (self.page("a"), self.page("a", "third")))
        self.run_update("--reviewed", "a")
        self.pages[self.A] = self.page("a", "fourth")
        self.run_update("--apply")
        self.assertEqual(prev.read_bytes(), self.page("a", "third"))

    def test_apply_says_when_there_is_no_previous_snapshot_to_diff(self):
        self.pages[self.A] = self.page("a", "second")
        write(self.kb / "snapshots-prev" / "a.md", "left over from an older cycle")
        code, report = self.report("--apply")  # a fresh clone: no local snapshot at all
        self.assertEqual(report["no_previous"], ["a"])
        self.assertFalse((self.kb / "snapshots-prev" / "a.md").exists())
        self.run_update("--reviewed", "a")
        write(self.kb / "snapshots" / "a.md", "tampered")  # a local file that does not match the lock is no baseline either
        self.pages[self.A] = self.page("a", "third")
        out = self.run_update("--apply")[1]
        self.assertIn("no previous snapshot to diff against: a; read those sources whole", out)

    def test_a_source_with_no_lock_entry_is_new_and_not_pending(self):
        write(self.kb / "sources.json", json.dumps(json.loads((self.kb / "sources.json").read_text(encoding="utf-8"))
                                                    + [{"id": "c", "url": self.C, "tier": 2, "topic": "cost"}]))
        code, report = self.report()
        self.assertEqual((code, [(c["id"], c["new"]) for c in report["changed_sources"]]), (3, [("c", True)]))
        code, report = self.report("--apply")
        self.assertEqual(report["no_previous"], [])
        self.assertFalse((self.kb / "pending.json").exists())
        self.assertIn("c", json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8")))
        self.assertEqual(self.report()[0], 0)

    def test_apply_refuses_when_kb_is_not_writable(self):
        self.pages[self.A] = self.page("a", "second")
        kb_update.kb_writable = lambda: False
        before = self.tree()
        code, out, err = self.run_update("--apply")
        self.assertEqual(code, 2)
        self.assertIn("not writable", err)
        self.assertEqual((out, self.asked, self.tree()), ("", [], before))
        self.assertEqual(self.run_update("--reviewed", "all")[0], 2)

    def test_apply_refuses_outside_a_working_clone(self):
        (self.root / ".git").rmdir()
        code, out, err = self.run_update("--apply")
        self.assertEqual((code, out, self.asked), (2, "", []))
        self.assertIn("no .git", err)
        cache = pathlib.Path(self.root.parent) / "plugins" / "cache" / "p"
        (cache / ".git").mkdir(parents=True)
        write(cache / "kb" / "sources.json", "[]")
        kb_update.KB = cache / "kb"
        code, _, err = self.run_update("--apply")
        self.assertEqual(code, 2)
        self.assertIn("plugin cache", err)

    def test_apply_applies_nothing_when_a_source_failed_unless_partial(self):
        del self.pages[self.A]
        self.pages[self.B] = self.page("b", "second")
        before = self.tree()
        code, out, err = self.run_update("--apply")
        self.assertEqual((code, self.tree()), (3, before))
        self.assertIn("nothing applied", err)
        self.assertNotIn("next:", out)
        self.patch(kb_fetch, "today_utc", lambda: "2030-01-02")
        self.run_update("--apply", "--partial")
        lock = json.loads((self.kb / "snapshots.lock.json").read_text(encoding="utf-8"))
        self.assertEqual((lock["a"]["fetched"], lock["b"]["fetched"]), ("2026-11-01", "2030-01-02"))
        self.assertEqual(list(self.pending()["sources"]), ["b"])

    def test_a_local_snapshot_that_differs_from_the_lock_is_restored_by_apply(self):
        write(self.kb / "snapshots" / "a.md", "tampered")
        code, report = self.report()
        self.assertEqual((code, report["snapshot_mismatch"]), (4, ["a"]))
        self.assertEqual(self.report("--apply")[1]["restored_snapshots"], ["a", "b"])
        self.assertEqual((self.kb / "snapshots" / "a.md").read_bytes(), self.page("a"))
        self.assertEqual((self.kb / "snapshots" / "b.md").read_bytes(), self.page("b"))
        self.assertEqual(self.report()[0], 0)

    def test_an_index_that_parses_to_nothing_or_too_little_is_not_accepted(self):
        self.pages[self.IDX] = b"<html>maintenance</html>"
        code, report = self.report()
        self.assertEqual((code, [f["id"] for f in report["failed"]]), (4, [self.IDX]))
        self.assertIn("0 urls", report["failed"][0]["error"])
        self.pages[self.IDX] = b"- [One](https://docs.test/one.md): x\n"
        write(self.kb / "index.lock.json", json.dumps({self.IDX: [f"https://docs.test/{n}.md" for n in "abcd"]}))
        self.assertEqual(self.report()[1]["failed"][0]["id"], self.IDX)
        index_lock = (self.kb / "index.lock.json").read_bytes()
        self.run_update("--apply", "--partial")
        self.assertEqual((self.kb / "index.lock.json").read_bytes(), index_lock)

    def test_an_unknown_only_id_is_a_usage_error_before_any_download(self):
        self.assertEqual(self.run_update("--only", "a,nope")[0], 2)
        self.assertEqual(self.asked, [])

    def test_out_must_be_outside_the_plugin(self):
        inside = self.kb / "report.json"
        code, _, err = self.run_update("--out", str(inside))
        self.assertEqual((code, inside.exists(), self.asked), (2, False, []))
        outside = self.root.parent / "elsewhere" / "report.json"
        self.assertEqual(self.run_update("--out", str(outside))[0], 0)
        self.assertEqual(json.loads(outside.read_text(encoding="utf-8"))["exit"], 0)

    def test_an_unreadable_claim_line_makes_the_check_incomplete(self):
        write(self.kb / "claims" / "bad.jsonl", "{not json\n")
        code, report = self.report()
        self.assertEqual((code, report["unreadable_claim_lines"]), (4, 1))

    def test_a_write_that_fails_leaves_the_old_file_and_no_temporary(self):
        self.pages[self.A] = self.page("a", "second")
        lock = (self.kb / "snapshots.lock.json").read_bytes()
        real = kb_fetch.os.replace

        def failing(src, dst, *a, **k):
            if pathlib.Path(dst).name == "snapshots.lock.json":
                raise OSError("disk full")
            return real(src, dst, *a, **k)
        self.patch(kb_fetch.os, "replace", failing)
        with self.assertRaises(OSError):
            self.run_update("--apply")
        self.patch(kb_fetch.os, "replace", real)
        self.assertEqual((self.kb / "snapshots.lock.json").read_bytes(), lock)
        self.assertEqual([p.name for p in self.kb.rglob("*.tmp")], [])
        self.assertEqual(list(self.pending()["sources"]), ["a"])  # pending went first, so the run still flags a
        self.assertEqual(self.report()[0], 3)

    def test_only_limits_the_sources_and_skips_the_indexes(self):
        self.run_update("--only", "b")
        self.assertEqual(self.asked, [self.B])


class QueryTest(unittest.TestCase):
    """kb.py against a temporary kb/."""

    def claim(self, cid, topic, kind="fact", scope=("all",), source="s"):
        return json.dumps({"id": cid, "topic": topic, "kind": kind, "applies_to": list(scope), "claim": f"claim {cid}", "why": "w",
                           "check": "k", "quote": "a quote long enough to pass", "source": source})

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.kb = pathlib.Path(tmp.name)
        write(self.kb / "claims" / "c.jsonl", "\n".join([
            self.claim("skills-001", "skills"), self.claim("hooks-001", "hooks", "practice"),
            self.claim("hooks-002", "hooks", scope=("claude-opus-5-5",), source="bd"), self.claim("hooks-003", "hooks", scope=("claude-code",), source="loc")]) + "\n")
        write(self.kb / "sources.json", json.dumps([{"id": "s", "url": "https://docs.test/s.md"}, {"id": "bd", "bundled": "shared/x.md"},
                                                    {"id": "loc", "path": "notes/y.md"}]))
        write(self.kb / "core.json", json.dumps({"place": {"principle": "Put it where it loads.", "claims": ["skills-001", "hooks-001"]}}))
        old = kb_query.KB
        self.addCleanup(setattr, kb_query, "KB", old)
        kb_query.KB = self.kb

    def query(self, *argv):
        raw, err = io.BytesIO(), io.StringIO()
        text = io.TextIOWrapper(raw, encoding="utf-8")
        with contextlib.redirect_stdout(text), contextlib.redirect_stderr(err):
            try:
                code = kb_query.main(list(argv))
            except SystemExit as exc:  # argparse misuse
                code = exc.code
        text.flush()
        return code, raw.getvalue().decode("utf-8"), err.getvalue()

    def test_an_empty_valid_selection_is_exit_1_and_an_invalid_value_is_exit_2(self):
        code, _, err = self.query("show", "skills", "--kind", "practice")
        self.assertEqual(code, 1)
        self.assertIn("no claims match", err)
        code, _, err = self.query("show", "nonsense")
        self.assertEqual(code, 2)
        self.assertIn("Topics: hooks, skills", err)
        self.assertEqual(self.query("show", "skills", "--kind", "typo")[0], 2)
        self.assertEqual(self.query("show", "skills", "--model", "sonnet")[0], 2)
        self.assertEqual(self.query("cite", "nope-1")[0], 2)
        self.assertEqual(self.query("core", "nope")[0], 2)
        self.assertEqual(self.query("model", "nonsense")[0], 2)
        self.assertEqual(self.query("model", "claude-zzz-9")[0], 1)

    def test_spaces_around_commas_are_ignored(self):
        code, out, _ = self.query("show", "skills, hooks", "--brief", "--model", " claude-opus-5-5 ")
        self.assertEqual(code, 0)
        self.assertIn("4 claims", out)
        self.assertIn("2 claims", self.query("cite", "skills-001, hooks-001")[1])

    def test_a_model_no_claim_names_is_a_note_not_an_error(self):
        code, out, err = self.query("show", "hooks", "--model", "claude-zzz-9", "--brief")
        self.assertEqual(code, 0)
        self.assertIn("may predate it", err)
        self.assertNotIn("hooks-002", out)

    def test_malformed_data_gets_a_diagnosis_not_a_traceback(self):
        write(self.kb / "claims" / "bad.jsonl", "{not json\n")
        code, _, err = self.query("topics")
        self.assertEqual(code, 3)
        self.assertIn("bad.jsonl:1", err)
        self.assertIn("kb_gate.py", err)
        (self.kb / "claims" / "bad.jsonl").unlink()
        write(self.kb / "claims" / "bad.jsonl", json.dumps({"id": "x-1"}) + "\n")
        self.assertEqual(self.query("topics")[0], 3)
        (self.kb / "claims" / "bad.jsonl").unlink()
        write(self.kb / "core.json", "{")
        self.assertEqual(self.query("core", "place")[0], 3)

    def test_cite_says_where_a_bundled_or_local_source_lives_and_core_does_not_call_everything_documentation(self):
        out = self.query("cite", "hooks-002,hooks-003,skills-001")[1]
        self.assertIn("bundled with Claude Code (a file of the claude-api skill, no URL): shared/x.md", out)
        self.assertIn("local file: notes/y.md", out)
        self.assertIn("https://docs.test/s.md", out)
        head = self.query("core", "place")[1].splitlines()[0]
        self.assertEqual(head, "What Anthropic's published material says, in short: Put it where it loads.")

    def test_claims_whose_source_is_pending_are_marked(self):
        write(self.kb / "pending.json", json.dumps({"sources": {"s": "2026-11-27"}}))
        for argv in (["cite", "skills-001"], ["show", "skills", "--brief"], ["core", "place"]):
            code, out, _ = self.query(*argv)
            self.assertEqual(code, 0)
            self.assertIn("skills-001", out)
            self.assertIn("[source changed on 2026-11-27; claim not re-reviewed]", out)
        self.assertNotIn("not re-reviewed", self.query("cite", "hooks-003")[1])
        (self.kb / "pending.json").unlink()
        self.assertNotIn("not re-reviewed", self.query("cite", "skills-001")[1])


class BytecodeTest(unittest.TestCase):
    def test_no_script_leaves_a_pycache_when_run_without_dash_B(self):
        """SECURITY promises these scripts write nothing; an import of a sibling would write scripts/__pycache__."""
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        with tempfile.TemporaryDirectory() as tmp:
            scripts = pathlib.Path(tmp) / "scripts"
            scripts.mkdir()
            for name in ("kb.py", "kb_fetch.py", "kb_gate.py", "kb_update.py"):
                (scripts / name).write_bytes((ROOT / "scripts" / name).read_bytes())
            for name in ("kb.py", "kb_fetch.py", "kb_gate.py", "kb_update.py"):
                out = subprocess.run([sys.executable, str(scripts / name), "--help"], capture_output=True, text=True, env=env)
                self.assertEqual(out.returncode, 0, name + out.stderr)
            self.assertEqual(sorted(p.name for p in scripts.iterdir()), ["kb.py", "kb_fetch.py", "kb_gate.py", "kb_update.py"])


class RepositoryKnowledgeBaseTest(unittest.TestCase):
    def test_harness_numbers_are_backed_by_their_claims(self):
        """A number the script depends on must still be stated by the claim it cites."""
        claims = {}
        for path in (ROOT / "kb" / "claims").glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                claim = json.loads(line)
                claims[claim["id"]] = claim
        harness = json.loads((ROOT / "kb" / "harness.json").read_text(encoding="utf-8"))
        for name, entry in harness.items():
            if name.startswith("_"):
                continue
            self.assertIn(entry["claim"], claims, name)
            self.assertIn(entry["stated_as"], claims[entry["claim"]]["quote"], name)

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

    def test_core_questions_name_real_general_claims(self):
        claims = {}
        for path in (ROOT / "kb" / "claims").glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                claim = json.loads(line)
                claims[claim["id"]] = claim
        core = json.loads((ROOT / "kb" / "core.json").read_text(encoding="utf-8"))
        for question, entry in core.items():
            self.assertTrue(entry["principle"].strip(), question)
            self.assertLessEqual(len(entry["claims"]), 14, question)
            for cid in entry["claims"]:
                self.assertIn(cid, claims, question)
                self.assertTrue(set(claims[cid]["applies_to"]) & {"all", "claude-code"}, f"{question}: {cid} is tied to a model")

    def test_query_script_selects_by_topic_and_model(self):
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "kb.py"), "show", "model", "--model", "claude-opus-5-5"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("[claude-haiku-5-5]", out.stdout)
        miss = subprocess.run([sys.executable, str(ROOT / "scripts" / "kb.py"), "cite", "nope-1"], capture_output=True, text=True)
        self.assertEqual(miss.returncode, 2)


if __name__ == "__main__":
    unittest.main()
