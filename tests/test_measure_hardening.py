"""Tests for the hardened measurement (scripts/measure.py): one per behavior added after the publication audit.

Every test builds its own setup under a temporary directory and never reads the developer's ~/.claude:
the search for instruction files above the project is bounded to that directory, and the environment
variable that moves the config directory is cleared. Run: python -m unittest discover tests
"""
import contextlib
import datetime as dt
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


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def iso(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def jsonl(rows) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def usage_row(when: str, mid: str, out: int = 10, written: int = 0, read: int = 0, model: str = "claude-opus-5-5") -> dict:
    return {"type": "assistant", "uuid": "u-" + mid, "sessionId": "s", "timestamp": when, "message": {
        "id": mid, "model": model, "content": [], "usage": {
            "input_tokens": 0, "output_tokens": out, "cache_read_input_tokens": read, "cache_creation_input_tokens": written}}}


def call_row(when: str, tool: str, args: dict) -> dict:
    return {"type": "assistant", "timestamp": when, "message": {"id": None, "content": [
        {"type": "tool_use", "id": f"t-{tool}-{sorted(args.values())}", "name": tool, "input": args}]}}


class Isolated(unittest.TestCase):
    """A temporary base with a user directory (base/home/.claude) and a project (base/proj)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name).resolve()
        self.home, self.project = self.base / "home" / ".claude", self.base / "proj"
        self.home.mkdir(parents=True)
        self.project.mkdir(parents=True)
        base = self.base

        def bounded(project):  # instruction files are looked for only inside the temporary base
            return [d for d in reversed([project, *project.parents]) if d == base or base in d.parents]

        for patcher in (mock.patch.object(measure, "ancestor_dirs", bounded),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def build(self, days: int = 0, **kw) -> dict:
        return measure.build(self.home, self.project, days, **kw)

    def settings(self, where: str, data: dict) -> None:
        path = {"user": self.home / "settings.json", "project": self.project / ".claude" / "settings.json",
                "local": self.project / ".claude" / "settings.local.json"}[where]
        write(path, json.dumps(data))

    def plugin(self, key: str, files: dict, scope: str = "user", project_path=None, folder=None) -> pathlib.Path:
        """Install a plugin: its files, and an entry in installed_plugins.json."""
        folder = folder or self.home / "plugins" / "cache" / "mk" / key.split("@")[0] / "1.0.0"
        for rel, text in files.items():
            write(folder / rel, text)
        record = self.home / "plugins" / "installed_plugins.json"
        data = json.loads(record.read_text(encoding="utf-8")) if record.is_file() else {"version": 2, "plugins": {}}
        entry = {"scope": scope, "installPath": str(folder), "version": "1.0.0"}
        if project_path:
            entry["projectPath"] = str(project_path)
        data["plugins"].setdefault(key, []).append(entry)
        write(record, json.dumps(data))
        return folder

    def transcript(self, name: str, rows) -> pathlib.Path:
        return write(self.home / "projects" / "p" / f"{name}.jsonl", jsonl(rows))

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = measure.main([str(a) for a in args])
            except SystemExit as exc:  # argparse exits on its own for misuse
                code = exc.code
        return code, out.getvalue(), err.getvalue()


SKILL = "---\nname: {name}\ndescription: {desc}\n---\nbody\n"


class InventoryTest(Isolated):
    def test_a_plugin_with_its_skill_at_the_root_is_inventoried(self):
        self.settings("user", {"enabledPlugins": {"solo@mk": True, "bare@mk": True, "both@mk": True, "decl@mk": True}})
        self.plugin("solo@mk", {"SKILL.md": SKILL.format(name="solo-skill", desc="Does one thing"), "references/a.md": "x"})
        self.plugin("bare@mk", {"SKILL.md": "---\ndescription: No name here\n---\nbody\n"})
        self.plugin("both@mk", {"SKILL.md": SKILL.format(name="ignored", desc="x"),
                                "skills/real/SKILL.md": SKILL.format(name="real", desc="Listed from skills")})
        self.plugin("decl@mk", {"SKILL.md": SKILL.format(name="declared", desc="x"),
                                ".claude-plugin/plugin.json": json.dumps({"name": "decl", "skills": ["./extra/"]})})
        doc = self.build()
        skills = {s["qualified"]: s for s in doc["skills"]}
        self.assertEqual(sorted(skills), ["bare:bare", "both:real", "solo:solo-skill"])  # the name, else the plugin's name
        self.assertEqual(skills["solo:solo-skill"]["scope"], "plugin:solo")
        layouts = {p["name"]: p["installs"][0]["layout"] for p in doc["plugins"]}
        self.assertEqual(layouts["solo"], "SKILL.md at the plugin root")
        self.assertEqual(layouts["both"], "skills/ folder")
        self.assertTrue(any("decl (skills)" in line for line in doc["not_measured"]))  # a manifest path it does not follow

    def test_a_higher_precedence_false_undoes_a_true(self):
        self.plugin("p@mk", {"SKILL.md": SKILL.format(name="p", desc="x")})
        self.plugin("q@mk", {"SKILL.md": SKILL.format(name="q", desc="x")})
        self.settings("user", {"enabledPlugins": {"p@mk": True, "q@mk": False}})
        self.settings("local", {"enabledPlugins": {"p@mk": False, "q@mk": True}})
        doc = self.build()
        self.assertEqual([s["qualified"] for s in doc["skills"]], ["q:q"])
        decided = {p["name"]: (p["enabled"], p["decided_by"]) for p in doc["plugins"]}
        self.assertEqual(decided, {"p": (False, "local"), "q": (True, "local")})

    def test_an_install_entry_counts_only_for_its_own_project(self):
        self.settings("user", {"enabledPlugins": {"mine@mk": True, "theirs@mk": True}})
        self.plugin("mine@mk", {"SKILL.md": SKILL.format(name="mine", desc="x")}, scope="local", project_path=self.project)
        self.plugin("theirs@mk", {"SKILL.md": SKILL.format(name="theirs", desc="x")}, scope="local", project_path=self.base / "other")
        doc = self.build()
        self.assertEqual([s["qualified"] for s in doc["skills"]], ["mine:mine"])
        self.assertTrue(any("theirs@mk" in line and "another project" in line for line in doc["not_measured"]))

    def test_listing_cap_comes_from_settings_and_a_missing_description_falls_back_to_the_first_body_line(self):
        self.settings("user", {"skillListingMaxDescChars": 10})
        write(self.home / "skills" / "long" / "SKILL.md", SKILL.format(name="long", desc="x" * 50))
        write(self.home / "skills" / "nodesc" / "SKILL.md", "---\nname: nodesc\n---\n\nFirst line of the body\nsecond\n")
        doc = self.build()
        skills = {s["name"]: s for s in doc["skills"]}
        self.assertEqual(doc["skill_listing_cap"]["chars"], 10)
        self.assertIn("skillListingMaxDescChars", doc["skill_listing_cap"]["source"])
        self.assertEqual((skills["long"]["listing_chars"], skills["long"]["always_est_tokens"], skills["long"]["listing_truncated"]),
                         (50, measure.est_tokens(10), True))
        self.assertEqual(skills["nodesc"]["listing_chars"], len("First line of the body"))
        self.assertIn("first non-empty body line", skills["nodesc"]["description_source"])
        self.assertEqual(skills["long"]["description_source"], "frontmatter")

    def test_skill_overrides_with_a_value_that_is_not_a_string_do_not_crash(self):
        self.settings("user", {"skillOverrides": {"a": ["x"], "b": 5, "c": "off"}})
        for name in "abc":
            write(self.home / "skills" / name / "SKILL.md", SKILL.format(name=name, desc="x"))
        doc = self.build()
        skills = {s["name"]: s for s in doc["skills"]}
        self.assertEqual((skills["a"]["visibility"], skills["b"]["visibility"], skills["c"]["visibility"]), ("on", "on", "off"))
        self.assertTrue(any("skillOverrides" in n for n in skills["a"]["parse_notes"]))
        self.assertEqual(doc["settings"]["files"][0]["skillOverrides"], {"a": "(other)", "b": "(other)", "c": "off"})


class InstructionTest(Isolated):
    def setUp(self):
        super().setUp()
        write(self.project / "CLAUDE.md", "p" * 40)
        write(self.project / "AGENTS.md", "a" * 400)

    def agents_md(self, doc):
        return next(f for f in doc["instruction_files"] if f["path"].endswith("AGENTS.md"))

    def mode(self, value):
        return {"pluginConfigs": {"cc-plugin-agents-md@builtin": {"options": {"instructionFiles": value}}}}

    def test_the_configured_instruction_mode_is_applied(self):
        doc = self.build()
        self.assertEqual((doc["instruction_mode"]["value"], self.agents_md(doc)["loads"]), ("claude-md-or-agents-md", "only if no CLAUDE.md is found"))
        self.settings("user", self.mode("claude-md-and-agents-md"))
        doc = self.build()
        self.assertEqual(self.agents_md(doc)["loads"], "session start")
        self.assertEqual(doc["fixed_context_est_tokens"]["instruction_files"], measure.est_tokens(40) + measure.est_tokens(400))
        self.settings("user", self.mode("claude-md"))
        self.assertIn("not loaded", self.agents_md(self.build())["loads"])
        self.settings("user", self.mode("managed-only"))
        doc = self.build()
        self.assertEqual(doc["fixed_context_est_tokens"]["instruction_files"], 0)
        self.assertTrue(all("managed-only" in f["loads"] for f in doc["instruction_files"]))

    def test_an_instruction_mode_in_project_settings_is_ignored_and_said_so(self):
        self.settings("project", self.mode("claude-md-and-agents-md"))
        doc = self.build()
        self.assertEqual(doc["instruction_mode"]["value"], "claude-md-or-agents-md")
        self.assertIn("ignores it there", doc["instruction_mode"]["note"])
        self.assertTrue(any("instruction mode" in line for line in doc["not_measured"]))

    def test_imports_with_escaped_spaces_no_extension_and_in_code_spans(self):
        write(self.project / "CLAUDE.md", "See @Design\\ Docs/api.md, @README and `@SKIPPED` and @nothere.md.\n```\n@fenced.md\n```\n")
        for rel in ("Design Docs/api.md", "README", "SKIPPED", "fenced.md"):
            write(self.project / rel, "x" * 8)
        names = {pathlib.Path(f["path"]).name for f in self.build()["instruction_files"]}
        self.assertTrue({"api.md", "README"} <= names)
        self.assertFalse({"SKIPPED", "fenced.md"} & names)

    def test_a_drive_path_import_is_read_where_it_can_be_and_a_tilde_needs_a_known_home(self):
        write(self.base / "mine" / "n.md", "x" * 8)
        write(self.project / "CLAUDE.md", f"@{self.base / 'mine' / 'n.md'} and @~/n2.md")
        write(self.base / "n2.md", "y" * 8)
        doc = self.build(user_home=None)
        names = {pathlib.Path(f["path"]).name for f in doc["instruction_files"]}
        self.assertIn("n.md", names)  # an absolute path, with a drive letter on Windows
        self.assertNotIn("n2.md", names)  # `~` is not the auditor's home when the audited user's is unknown
        self.assertTrue(any("left unresolved" in line for line in doc["not_measured"]))
        names = {pathlib.Path(f["path"]).name for f in self.build(user_home=self.base)["instruction_files"]}
        self.assertIn("n2.md", names)


class ConfigLocationTest(Isolated):
    def test_user_config_follows_the_config_directory(self):
        env = str(self.home)
        path, basis = measure.resolve_user_config(self.home, None, env)
        self.assertEqual(path, self.home / ".claude.json")
        self.assertIn("CLAUDE_CONFIG_DIR", basis)
        self.assertEqual(measure.resolve_user_config(self.home, None, None)[0], self.home.parent / ".claude.json")
        custom = self.base / "custom-config"
        self.assertEqual(measure.resolve_user_config(custom, None, None)[0], custom / ".claude.json")
        self.assertEqual(measure.resolve_user_config(self.home, str(self.base / "x.json"), env), (self.base / "x.json", "--user-config"))

    def test_the_server_names_come_from_the_resolved_file(self):
        config = self.base / "cfg"
        write(config / ".claude.json", json.dumps({"mcpServers": {"inside": {"type": "http", "env": {"K": "SECRET"}}}}))
        write(self.base / ".claude.json", json.dumps({"mcpServers": {"beside": {}}}))
        os.environ["CLAUDE_CONFIG_DIR"] = str(config)
        out = self.base / "m.json"
        code, _, err = self.cli("--home", config, "--project", self.project, "--days", 0, "--out", out)
        self.assertEqual(code, 0, err)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([s["name"] for s in doc["settings"]["mcp_servers"]], ["inside"])
        self.assertEqual(doc["user_config"]["path"], str(config / ".claude.json"))
        self.assertTrue(doc["user_config"]["found"])
        self.assertNotIn("SECRET", json.dumps(doc))
        # --user-config overrides
        code, _, err = self.cli("--home", config, "--project", self.project, "--days", 0, "--out", out,
                                "--user-config", self.base / ".claude.json")
        self.assertEqual(code, 0, err)
        self.assertEqual([s["name"] for s in json.loads(out.read_text(encoding="utf-8"))["settings"]["mcp_servers"]], ["beside"])


class HookPathsTest(Isolated):
    def test_variables_with_an_unknown_value_are_unresolved_not_missing(self):
        home = self.base / "cfg"  # not named .claude: the user's home cannot be told from it
        home.mkdir()
        for command in ("python $HOME/h.py", 'python "$HOME"/h.py', "cmd /c %USERPROFILE%\\h.cmd", "python ~/h.py"):
            paths = measure.hook_script_paths(command, home, self.project, user_home=None)
            self.assertEqual((paths["missing"], paths["missing_relative"]), ([], []), command)
            self.assertEqual(len(paths["unresolved"]), 1, command)
        known = measure.hook_script_paths("python $HOME/h.py", home, self.project, user_home=self.base)
        self.assertEqual(len(known["missing"]), 1)
        write(self.base / "h.py", "")
        self.assertEqual(measure.hook_script_paths("python $HOME/h.py", home, self.project, user_home=self.base)["missing"], [])

    def test_windows_syntax_is_not_read_as_posix_shell(self):
        write(self.project / "hooks" / "x.ps1", "")
        for command in ('powershell -File "%CLAUDE_PROJECT_DIR%\\hooks\\x.ps1"', 'pwsh -File $env:CLAUDE_PROJECT_DIR\\hooks\\x.ps1'):
            paths = measure.hook_script_paths(command, self.home, self.project)
            self.assertEqual(paths["missing"], [], command)
            self.assertIn("Windows", paths["note"])
        self.assertEqual(measure.hook_script_paths("powershell -File C:\\no\\such\\dir\\x.ps1", self.home, self.project)["missing"] != [],
                         os.name == "nt")  # a drive path can be checked only where drives exist

    def test_relative_and_rooted_paths_are_reported_apart(self):
        paths = measure.hook_script_paths("node scripts/gone.js", self.home, self.project)
        self.assertEqual((paths["missing"], paths["missing_relative"]), ([], ["scripts/gone.js"]))
        rooted = measure.hook_script_paths("python /no/such/hook.py", self.home, self.project)
        self.assertEqual(rooted["missing"] != [], os.name != "nt")  # Git Bash style paths have no known base on Windows
        self.assertEqual(rooted["unresolved"] != [], os.name == "nt")
        self.settings("user", {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "node scripts/gone.js $FOO/x.sh"}]}]}})
        hook = self.build()["settings"]["hooks"][0]
        self.assertEqual((hook["scripts_missing"], hook["scripts_missing_relative_to_project"], hook["scripts_unresolved"]),
                         ([], ["scripts/gone.js"], ["$FOO/x.sh"]))


class HistoryTest(Isolated):
    def test_timestamps_are_compared_as_instants_not_as_text(self):
        now = dt.datetime.now(dt.timezone.utc)

        def at(delta, hours):  # the instant now+delta, written with an offset
            when = (now + delta).astimezone(dt.timezone(dt.timedelta(hours=hours)))
            return when.strftime("%Y-%m-%dT%H:%M:%S.000") + f"{hours:+03d}:00"

        self.transcript("s", [usage_row(at(-dt.timedelta(hours=25), 10), "old", out=100),     # outside a 1-day window, text reads as recent
                              usage_row(at(-dt.timedelta(hours=23), -10), "new", out=7)])    # inside it, text reads as old
        use = self.build(days=1)["usage"]
        self.assertEqual(use["tokens_total"]["output"], 7)

    def test_the_gap_between_requests_is_real_time(self):
        now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)
        later = (now + dt.timedelta(minutes=2)).astimezone(dt.timezone(dt.timedelta(hours=5)))
        self.transcript("s", [usage_row(iso(now), "a", written=100000),
                              usage_row(later.strftime("%Y-%m-%dT%H:%M:%S.000+05:00"), "b", written=100000)])
        causes = self.build(days=30)["usage"]["cache_rebuilds"]["by_cause"]
        self.assertEqual(len(causes), 1)
        self.assertTrue(next(iter(causes)).startswith("other"), causes)  # 2 minutes apart, not 5 hours 2 minutes

    def test_an_old_modification_time_does_not_hide_recent_rows(self):
        now = iso(dt.datetime.now(dt.timezone.utc))
        recent = self.transcript("copied", [usage_row(now, "r", out=5)])
        old = self.transcript("ancient", [usage_row("2020-01-01T00:00:00.000Z", "o", out=900)])
        for path in (recent, old):
            os.utime(path, (978307200, 978307200))  # both claim to be from 2001
        use = self.build(days=30)["usage"]
        self.assertEqual(use["tokens_total"].get("output", 0), 5)
        self.assertEqual(use["coverage"].get("files_wholly_before_window", 0), 1)  # skipped only because its own rows say so
        self.assertEqual(use["coverage"].get("files_read", 0), 1)

    def test_rebuild_causes_are_labelled_as_inference_and_the_definition_matches_the_test(self):
        now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        self.transcript("s", [usage_row(iso(now), "a", written=100000),
                              usage_row(iso(now + dt.timedelta(minutes=30)), "b", written=100000)])
        rebuilds = self.build(days=30)["usage"]["cache_rebuilds"]
        self.assertIn("hypothesis", rebuilds["basis"])
        self.assertIn("more than half", rebuilds["definition"])
        self.assertNotIn("at least half", rebuilds["definition"])
        self.assertEqual(rebuilds["main_requests_considered"], 2)

    def test_names_keep_their_namespace_when_use_is_attributed(self):
        helper = "---\nname: helper\ndescription: Plugin helper\n---\nx\n"
        self.plugin("rev@mk", {"skills/review/SKILL.md": SKILL.format(name="review", desc="Plugin review"), "agents/helper.md": helper})
        self.plugin("rev2@mk", {"agents/helper.md": helper})
        self.settings("user", {"enabledPlugins": {"rev@mk": True, "rev2@mk": True}})
        write(self.home / "skills" / "review" / "SKILL.md", SKILL.format(name="review", desc="Own review"))
        now = iso(dt.datetime.now(dt.timezone.utc))
        self.transcript("a", [call_row(now, "Skill", {"skill": "rev:review"}), call_row(now, "Agent", {"subagent_type": "ghost:helper"}),
                              call_row(now, "Agent", {"subagent_type": "rev:helper"})])
        doc = self.build(days=30)
        self.assertEqual(doc["never_invoked_in_window"]["skills"], ["review"])  # the user's skill, not the plugin's
        self.assertEqual(doc["never_invoked_in_window"]["agents"], ["rev2:helper"])  # same bare name, other plugin
        self.assertEqual(doc["spawned_without_definition_here"], ["ghost:helper"])
        self.assertEqual(doc["usage"]["share_of_spawns_to_agents_defined_here"], 0.5)
        # a bare name goes to the user's own piece when there is one, and fits several plugin pieces otherwise:
        # then nobody is called unused, and the name is listed as ambiguous
        self.transcript("b", [call_row(now, "Skill", {"skill": "review"}), call_row(now, "Agent", {"subagent_type": "helper"})])
        doc = self.build(days=30)
        self.assertEqual(doc["never_invoked_in_window"], {"skills": [], "agents": []})
        self.assertEqual(doc["usage"]["attribution_ambiguous"], {"skills": [], "agents": ["helper"]})


class ComparisonAndCommandLineTest(Isolated):
    def measure_to(self, name: str, *extra):
        out = self.base / name
        code, _, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--out", out, *extra)
        self.assertEqual(code, 0, err)
        return out

    def test_every_measurement_carries_a_schema_version_and_the_policy(self):
        doc = self.build()
        self.assertEqual((doc["schema_version"], doc["kind"]), (1, "setup"))
        self.assertEqual(doc["policy"]["overlap_min_jaccard"], measure.OVERLAP_MIN_JACCARD)
        self.assertEqual(doc["policy"]["overlap_top"], measure.TOP_OVERLAPS)
        write(self.base / "s" / "SKILL.md", SKILL.format(name="s", desc="x"))
        piece = measure.piece(self.base / "s")
        self.assertEqual((piece["schema_version"], piece["kind"], piece["piece_type"]), (1, "piece", "skill"))
        self.assertIn("policy", piece)
        self.assertTrue(piece["not_measured"])

    def test_a_baseline_is_validated_before_it_is_compared(self):
        doc = self.build()
        for change, needle in (({"kind": "piece"}, "not a setup"), ({"schema_version": 0}, "schema_version"),
                               ({"project": str(self.base / "elsewhere")}, "different project")):
            with self.assertRaises(measure.InputError, msg=change) as caught:
                measure.compare({**doc, **change}, doc)
            self.assertIn(needle, str(caught.exception))
        with self.assertRaises(measure.InputError):
            measure.compare({**doc, "skills": "damaged"}, doc)

    def test_a_baseline_missing_a_key_is_refused_before_anything_is_written(self):
        write(self.base / "marker", "")
        self.transcript("s", [usage_row(iso(dt.datetime.now(dt.timezone.utc)), "a", out=5)])
        good = self.build(days=30)
        damaged = {
            "no generated": {k: v for k, v in good.items() if k != "generated"},
            "settings without hooks": {**good, "settings": {k: v for k, v in good["settings"].items() if k != "hooks"}},
            "hooks not a list": {**good, "settings": {**good["settings"], "hooks": 3}},
            "no never_invoked": {k: v for k, v in good.items() if k != "never_invoked_in_window"},
            "no sessions": {**good, "usage": {k: v for k, v in good["usage"].items() if k != "sessions"}},
            "text where a number goes": {**good, "fixed_context_est_tokens": {"total": "many"}},
            "no read_scope": {k: v for k, v in good.items() if k != "read_scope"},
        }
        for label, doc in damaged.items():
            baseline = write(self.base / "damaged.json", json.dumps(doc))
            out = self.base / "new.json"
            code, stdout, err = self.cli("--home", self.home, "--project", self.project, "--days", 30, "--out", out, "--compare", baseline)
            self.assertEqual(code, 2, f"{label}: {err}")
            self.assertIn("damaged", err, label)
            self.assertFalse(out.exists(), f"{label}: --out was written before the baseline was refused")
            self.assertEqual(stdout, "", label)
        baseline = write(self.base / "good.json", json.dumps(good))
        code, _, err = self.cli("--home", self.home, "--project", self.project, "--days", 30, "--out", self.base / "new.json",
                                "--compare", baseline)
        self.assertEqual(code, 0, err)

    def test_measurements_with_different_read_scopes_are_not_compared(self):
        write(self.base / "CLAUDE.md", "above the project")
        write(self.project / "CLAUDE.md", "in the project")
        open_scope = self.measure_to("open.json")
        confined = self.measure_to("confined.json", "--no-external-reads")
        for baseline, extra in ((open_scope, ("--no-external-reads",)), (confined, ())):
            out = self.base / "never.json"
            code, stdout, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--compare", baseline,
                                         "--out", out, *extra)
            self.assertEqual(code, 2, err)
            self.assertIn("different read scopes", err)
            self.assertFalse(out.exists())
        code, out, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--compare", confined,
                                  "--no-external-reads")
        self.assertEqual((code, "no measured difference" in out), (0, True), err)

    def test_measurements_that_read_different_user_configs_are_not_compared(self):
        baseline = self.measure_to("b.json")
        other = write(self.base / "other.json", json.dumps({"mcpServers": {"x": {}}}))
        code, _, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--compare", baseline,
                                "--user-config", other)
        self.assertEqual(code, 2)
        self.assertIn("different user-level .claude.json", err)

    def test_a_different_window_leaves_the_usage_rows_out_and_says_so(self):
        write(self.base / "marker", "")
        self.transcript("s", [usage_row(iso(dt.datetime.now(dt.timezone.utc)), "a", out=5)])
        before, after = self.build(days=30), self.build(days=7)
        text = measure.compare(before, after)
        self.assertIn("usage rows left out", text)
        self.assertNotIn("output tokens per session", text)
        self.assertNotIn("usage rows left out", measure.compare(before, before))

    def test_out_cannot_replace_the_baseline_it_compares_with(self):
        baseline = self.measure_to("before.json")
        kept = baseline.read_bytes()
        code, _, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--out", baseline, "--compare", baseline)
        self.assertEqual(code, 2)
        self.assertIn("same file", err)
        self.assertEqual(baseline.read_bytes(), kept)
        code, out, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--compare", baseline)
        self.assertEqual(code, 0, err)
        self.assertIn("no measured difference", out)

    def test_inputs_that_cannot_be_used_end_in_exit_2_with_a_message(self):
        baseline = self.measure_to("b.json")
        (self.base / "empty").mkdir()
        write(self.base / "notes.txt", "x")
        write(self.base / "bad.json", "{not json")
        write(self.base / "piece.json", json.dumps({"kind": "piece", "schema_version": 1}))
        cases = {
            "missing project": ["--home", self.home, "--project", self.base / "nope"],
            "missing home": ["--home", self.base / "nope", "--project", self.project],
            "negative days": ["--home", self.home, "--project", self.project, "--days", -1],
            "absurd days": ["--home", self.home, "--project", self.project, "--days", 10 ** 9],
            "out in a missing folder": ["--home", self.home, "--project", self.project, "--out", self.base / "no" / "o.json"],
            "out is a folder": ["--home", self.home, "--project", self.project, "--out", self.base / "empty"],
            "missing baseline": ["--home", self.home, "--project", self.project, "--compare", self.base / "nope.json"],
            "baseline not json": ["--home", self.home, "--project", self.project, "--compare", self.base / "bad.json"],
            "baseline of the wrong kind": ["--home", self.home, "--project", self.project, "--compare", self.base / "piece.json"],
            "missing user config": ["--home", self.home, "--project", self.project, "--user-config", self.base / "nope.json"],
            "folder without SKILL.md": ["--piece", self.base / "empty"],
            "piece that is not a skill or agent": ["--piece", self.base / "notes.txt"],
            "missing piece": ["--piece", self.base / "nope"],
            "piece with --home": ["--piece", baseline, "--home", self.home],
            "piece with --compare": ["--piece", self.base / "empty", "--compare", baseline],
            "piece with --days": ["--piece", self.base / "empty", "--days", 3],
        }
        for label, args in cases.items():
            code, out, err = self.cli(*args)
            self.assertEqual(code, 2, f"{label}: {err}")
            self.assertTrue(err.startswith("measure.py: "), f"{label}: {err!r}")
            self.assertNotIn("Traceback", err, label)

    def test_a_baseline_of_another_project_is_refused(self):
        baseline = self.measure_to("b.json")
        other = self.base / "other"
        other.mkdir()
        code, _, err = self.cli("--home", self.home, "--project", other, "--days", 0, "--compare", baseline)
        self.assertEqual(code, 2)
        self.assertIn("different project", err)

    def test_the_report_is_written_for_the_current_user_only_where_modes_exist(self):
        out = self.base / "r.json"
        write(out, "old")
        if os.name != "nt":
            os.chmod(out, 0o644)
        self.measure_to("r.json")
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["kind"], "setup")
        if os.name != "nt":
            self.assertEqual(out.stat().st_mode & 0o077, 0)
        self.assertIn("ACL", measure.__doc__)  # where modes do not apply, the docstring says what does

    def test_an_existing_report_is_restricted_before_the_new_content_goes_in(self):
        out = write(self.base / "r.json", "OLD")
        seen = []

        def fchmod(fd, mode):  # what is in the file at the moment its mode is restricted
            seen.append((mode, out.read_text(encoding="utf-8")))

        with mock.patch.object(measure, "HAS_MODES", True), mock.patch.object(os, "fchmod", fchmod, create=True):
            measure.write_private(out, "NEW-CONTENT")
        self.assertEqual(seen, [(0o600, "OLD")])  # restricted while it still held only the old text, never after the new one
        self.assertEqual(out.read_text(encoding="utf-8"), "NEW-CONTENT")
        measure.write_private(out, "SHORT")  # shorter text leaves nothing of the longer one behind
        self.assertEqual(out.read_text(encoding="utf-8"), "SHORT")

    @unittest.skipIf(os.name == "nt", "file modes do not exist on Windows")
    def test_a_wide_open_report_is_never_rewritten_in_place_with_its_old_mode(self):
        out = write(self.base / "r.json", "OLD")
        os.chmod(out, 0o666)
        measure.write_private(out, "NEW")
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)

    def test_a_report_that_cannot_be_written_is_exit_1_after_the_summary(self):
        out = write(self.base / "locked.json", "keep")
        os.chmod(out, 0o444)
        self.addCleanup(os.chmod, out, 0o644)
        if os.name != "nt" and os.geteuid() == 0:
            self.skipTest("root can write a read-only file")
        code, stdout, err = self.cli("--home", self.home, "--project", self.project, "--days", 0, "--out", out)
        self.assertEqual(code, 1)
        self.assertIn("could not write", err)
        self.assertIn("fixed context", stdout)
        self.assertEqual(out.read_text(encoding="utf-8"), "keep")

    def test_a_piece_can_be_written_with_out_and_an_agent_file_is_a_piece(self):
        agent = write(self.base / "a.md", "---\nname: a\ndescription: Reviews things\n---\nYou review.\n")
        out = self.base / "p.json"
        code, stdout, err = self.cli("--piece", agent, "--out", out)
        self.assertEqual(code, 0, err)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((written["piece_type"], written["name"]), ("agent", "a"))
        self.assertEqual(json.loads(stdout), written)

    def test_bundled_text_is_counted_in_characters_not_bytes(self):
        write(self.base / "s" / "SKILL.md", SKILL.format(name="s", desc="x"))
        write(self.base / "s" / "references" / "wide.md", "é" * 400)  # 800 bytes in UTF-8
        self.assertEqual(measure.piece(self.base / "s")["bundled"], {"references": {"files": 1, "est_tokens": 100}})

    def test_help_lists_every_flag_and_the_exit_codes(self):
        run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "measure.py"), "--help"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        for flag in ("--home", "--project", "--days", "--out", "--compare", "--piece", "--user-config", "--no-external-reads"):
            self.assertIn(flag, run.stdout)
            self.assertIn(flag, measure.__doc__)
        self.assertIn("Exit codes:", run.stdout)
        self.assertIn("Modes and combinations:", run.stdout)
        self.assertIn(measure._block("Exit codes"), run.stdout)


class FrontmatterNotesTest(unittest.TestCase):
    def test_what_the_reader_did_not_interpret_is_named_without_its_value(self):
        text = ("---\nname: x\ntools: {a: SECRETVAL}\nskills: |\n  one\ndescription: >\n  folded\n  text\nmodel: &anchor sonnet\n"
                "tools2:\n  - name: SECRETVAL\nbare line SECRETVAL\n---\nbody")
        parsed = measure.parse_frontmatter(text)
        notes = " | ".join(parsed["notes"])
        for expected in ("tools: an inline mapping", "skills: a block scalar", "description: a block scalar", "model: a YAML anchor",
                         "1 line(s)"):
            self.assertIn(expected, notes)
        self.assertNotIn("SECRETVAL", json.dumps(parsed["notes"]))
        self.assertEqual(parsed["meta"]["description"], "folded text")

    def test_missing_and_unclosed_frontmatter_are_distinguished(self):
        self.assertEqual(measure.parse_frontmatter("just text")["notes"], [])
        self.assertFalse(measure.parse_frontmatter("just text")["present"])
        unclosed = measure.parse_frontmatter("---\nname: x\nno end")
        self.assertIn("never closed", unclosed["notes"][0])
        self.assertEqual(unclosed["meta"], {})


class ConfinementTest(Isolated):
    def link_dir(self, link: pathlib.Path, target: pathlib.Path) -> None:
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            made = os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                                      capture_output=True).returncode == 0  # a junction needs no privilege
            if not made:
                self.skipTest("neither symbolic links nor junctions are available here")

    def link_file(self, link: pathlib.Path, target: pathlib.Path) -> None:
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("file symbolic links are not available here (the same check is made without a link below)")

    def subagent_transcript(self) -> pathlib.Path:
        now = iso(dt.datetime.now(dt.timezone.utc))
        return write(self.home / "projects" / "p" / "sess" / "subagents" / "agent-1.jsonl", jsonl([usage_row(now, "m", out=5)]))

    def test_ancestor_instruction_files_are_read_unless_reads_are_confined(self):
        write(self.base / "CLAUDE.md", "above the project")
        write(self.project / "CLAUDE.md", "in the project")
        doc = self.build()
        self.assertEqual({f["scope"] for f in doc["instruction_files"]}, {"ancestor", "project"})
        doc = self.build(confine=True)
        self.assertEqual({f["scope"] for f in doc["instruction_files"]}, {"project"})
        self.assertTrue(any("above the project" in line for line in doc["not_measured"]))
        self.assertTrue(doc["read_scope"]["confine_external_reads"])

    def test_an_import_outside_home_and_project_is_followed_only_when_not_confined(self):
        write(self.base / "outside" / "notes.md", "elsewhere")
        write(self.project / "CLAUDE.md", "@../outside/notes.md")
        imported = {f["path"]: f for f in self.build()["instruction_files"] if f["imported_by"]}
        self.assertTrue(all(f["external"] for f in imported.values()) and len(imported) == 1)
        doc = self.build(confine=True)
        self.assertEqual([f for f in doc["instruction_files"] if f["imported_by"]], [])
        self.assertTrue(any(p.endswith("notes.md") for p in doc["read_scope"]["skipped_outside_scope"]))

    def test_a_link_that_leaves_the_scope_is_followed_only_when_not_confined(self):
        write(self.base / "outside" / "target.md", "elsewhere")
        self.link_dir(self.project / "linked", self.base / "outside")
        write(self.project / "CLAUDE.md", "@linked/target.md")
        self.assertEqual(len([f for f in self.build()["instruction_files"] if f["imported_by"]]), 1)
        self.assertEqual(len([f for f in self.build(confine=True)["instruction_files"] if f["imported_by"]]), 0)

    def test_a_plugin_installed_outside_home_is_skipped_when_confined(self):
        self.settings("user", {"enabledPlugins": {"far@mk": True}})
        self.plugin("far@mk", {"SKILL.md": SKILL.format(name="far", desc="x")}, folder=self.base / "elsewhere" / "far")
        self.assertEqual([s["qualified"] for s in self.build()["skills"]], ["far:far"])
        doc = self.build(confine=True)
        self.assertEqual(doc["skills"], [])
        self.assertTrue(any("outside --home and --project" in line for line in doc["not_measured"]))

    def test_the_user_config_beside_home_is_not_read_when_confined_unless_named(self):
        write(self.home.parent / ".claude.json", json.dumps({"mcpServers": {"beside": {}}}))
        self.assertEqual([s["name"] for s in self.build()["settings"]["mcp_servers"]], ["beside"])
        self.assertEqual(self.build(confine=True)["settings"]["mcp_servers"], [])
        named = (self.home.parent / ".claude.json", "--user-config")
        self.assertEqual([s["name"] for s in self.build(confine=True, user_config=named)["settings"]["mcp_servers"]], ["beside"])

    def test_a_subagent_sidecar_that_is_a_link_out_of_scope_is_not_read_when_confined(self):
        self.subagent_transcript()
        outside = write(self.base / "outside" / "real.meta.json", json.dumps({"agentType": "planted"}))
        self.link_file(self.home / "projects" / "p" / "sess" / "subagents" / "agent-1.meta.json", outside)
        self.assertIn("planted", self.build(days=30)["usage"]["agent_runs"])
        doc = self.build(days=30, confine=True)
        self.assertEqual(list(doc["usage"]["agent_runs"]), ["(unknown)"])
        self.assertTrue(any(p.endswith("agent-1.meta.json") for p in doc["read_scope"]["skipped_outside_scope"]))

    def test_the_subagent_sidecar_goes_through_the_scanner(self):
        # the same check with no link: the scanner is told the sidecar is outside, and the file must stay unread
        self.subagent_transcript()
        write(self.home / "projects" / "p" / "sess" / "subagents" / "agent-1.meta.json", json.dumps({"agentType": "planted"}))
        self.assertIn("planted", self.build(days=30, confine=True)["usage"]["agent_runs"])  # inside the scope: read
        real_inside = measure.Scan.inside
        with mock.patch.object(measure.Scan, "inside", lambda scan, p: not p.name.endswith(".meta.json") and real_inside(scan, p)):
            doc = self.build(days=30, confine=True)
            unconfined = self.build(days=30)
        self.assertEqual(list(doc["usage"]["agent_runs"]), ["(unknown)"])
        self.assertIn("planted", unconfined["usage"]["agent_runs"])

    def test_a_piece_is_confined_before_anything_is_opened(self):
        skill = write(self.base / "s" / "SKILL.md", SKILL.format(name="s", desc="x"))
        real_inside = measure.Scan.inside
        opened = mock.Mock(side_effect=AssertionError("the file was opened before the scope check"))
        with mock.patch.object(measure.Scan, "inside", lambda scan, p: p.name != "SKILL.md" and real_inside(scan, p)), \
                mock.patch.object(pathlib.Path, "read_bytes", opened), mock.patch.object(pathlib.Path, "read_text", opened):
            with self.assertRaises(measure.InputError) as caught:
                measure.piece(skill.parent, confine=True)
        self.assertIn("--no-external-reads", str(caught.exception))
        opened.assert_not_called()
        self.assertEqual(measure.piece(skill.parent, confine=False)["name"], "s")

    def test_a_piece_whose_skill_file_is_a_link_out_of_its_folder_is_refused_when_confined(self):
        outside = write(self.base / "outside" / "SKILL.md", SKILL.format(name="far", desc="x"))
        (self.base / "s").mkdir()
        self.link_file(self.base / "s" / "SKILL.md", outside)
        self.assertEqual(measure.piece(self.base / "s")["name"], "far")
        with self.assertRaises(measure.InputError):
            measure.piece(self.base / "s", confine=True)
        code, _, err = self.cli("--piece", self.base / "s", "--no-external-reads")
        self.assertEqual(code, 2, err)

    def test_bundled_text_behind_a_link_out_of_the_folder_is_not_counted_when_confined(self):
        write(self.base / "s" / "SKILL.md", SKILL.format(name="s", desc="x"))
        write(self.base / "s" / "references" / "own.md", "a" * 40)
        write(self.base / "outside" / "far.md", "b" * 4000)
        self.link_dir(self.base / "s" / "linked", self.base / "outside")
        doc = measure.piece(self.base / "s", confine=True)
        self.assertEqual(doc["bundled"], {"references": {"files": 1, "est_tokens": 10}})
        self.assertTrue(doc["read_scope"]["confine_external_reads"])
        self.assertNotIn("linked", doc["bundled"])


if __name__ == "__main__":
    unittest.main()
