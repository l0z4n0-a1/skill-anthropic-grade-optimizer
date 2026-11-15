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
        self.assertEqual(miss.returncode, 1)


if __name__ == "__main__":
    unittest.main()
