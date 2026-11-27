"""Tests for scripts/backup.py: save, record, status and restore on files in a temporary directory.

Nothing here touches the developer's ~/.claude or the default store: every test passes --out.
Run: python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import backup  # noqa: E402

POSIX = backup.HAS_MODES


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = pathlib.Path(tmp.name).resolve()
        self.setup = self.base / "setup"
        self.setup.mkdir()
        self.store = self.base / "store"
        self.a = self.put("a.json", '{"token": "SECRET-A", "model": "opus"}\n')
        self.b = self.put("sub/b.md", "original b\n")
        self.new = self.setup / "created.py"  # absent at save time

    def put(self, name: str, text: str) -> pathlib.Path:
        path = self.setup / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = backup.main([str(a) for a in args])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def save(self, *paths) -> pathlib.Path:
        code, out, err = self.run_main("save", "--out", self.store, *(paths or (self.a, self.b, self.new)))
        self.assertEqual(code, 0, err)
        match = re.search(r"^folder: (.+)$", out, re.M)
        self.assertIsNotNone(match, out)
        return pathlib.Path(match.group(1))

    def edit(self):
        self.a.write_text('{"model": "sonnet"}\n', encoding="utf-8")
        self.new.write_text("print('new')\n", encoding="utf-8")
        self.b.unlink()

    def test_save_writes_a_manifest_with_hashes_absent_paths_and_copies(self):
        folder = self.save()
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        by_path = {e["path"]: e for e in manifest["files"]}
        a = by_path[str(self.a)]
        self.assertEqual(a["sha256"], backup.sha256(self.a.read_bytes()))
        self.assertEqual(a["size"], self.a.stat().st_size)
        self.assertEqual(a["mode"], f"{stat.S_IMODE(self.a.stat().st_mode):04o}")
        self.assertEqual((folder / a["copy"]).read_bytes(), self.a.read_bytes())
        gone = by_path[str(self.new)]
        self.assertEqual((gone["sha256"], gone["copy"], gone["size"], gone["mode"]), ("absent", None, None, None))
        self.assertTrue(all(e["post_edit_sha256"] is None for e in manifest["files"]))

    def test_save_prints_the_folder_and_a_restore_command_but_never_contents(self):
        code, out, err = self.run_main("save", "--out", self.store, self.a, self.b)
        self.assertEqual(code, 0, err)
        self.assertIn("restore with:", out)
        self.assertIn("restore", out.split("restore with:")[1])
        for text in (out, err):
            self.assertNotIn("SECRET-A", text)
            self.assertNotIn("original b", text)

    @unittest.skipUnless(POSIX, "POSIX modes")
    def test_the_store_the_backup_folder_and_the_copies_are_owner_only(self):
        folder = self.save()
        modes = {p: stat.S_IMODE(p.stat().st_mode) for p in (self.store, folder, folder / "files", folder / "manifest.json",
                                                                *(folder / "files").iterdir())}
        for path, mode in modes.items():
            self.assertEqual(mode & 0o077, 0, f"{path} is open to others: {mode:o}")

    def test_the_default_store_is_in_the_home_outside_claude_and_any_project(self):
        home = pathlib.Path.home().resolve()
        store = backup.DEFAULT_STORE.resolve()
        self.assertEqual(store.parent, home)
        self.assertNotIn(".claude", store.parts)
        self.assertNotEqual(store.parent, pathlib.Path.cwd().resolve())

    def test_a_folder_is_refused_with_exit_2_and_nothing_is_created(self):
        code, _, err = self.run_main("save", "--out", self.store, self.a, self.setup)
        self.assertEqual(code, 2)
        self.assertIn("is a folder", err)
        self.assertFalse(self.store.exists())

    def test_restore_puts_originals_back_deletes_created_files_and_is_idempotent(self):
        folder = self.save()
        self.edit()
        code, _, err = self.run_main("record", folder)
        self.assertEqual(code, 0, err)
        code, out, err = self.run_main("restore", folder)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.a.read_text(encoding="utf-8"), '{"token": "SECRET-A", "model": "opus"}\n')
        self.assertEqual(self.b.read_text(encoding="utf-8"), "original b\n")
        self.assertFalse(self.new.exists())
        self.assertNotIn("SECRET-A", out)
        code, out, err = self.run_main("restore", folder)
        self.assertEqual(code, 0, err)
        self.assertIn("nothing to restore", out)
        self.assertEqual(self.b.read_text(encoding="utf-8"), "original b\n")

    @unittest.skipUnless(POSIX, "POSIX modes")
    def test_restore_puts_the_mode_back(self):
        self.a.chmod(0o640)
        folder = self.save()
        self.a.write_text("edited\n", encoding="utf-8")
        self.a.chmod(0o600)
        self.run_main("record", folder)
        self.assertEqual(self.run_main("restore", folder)[0], 0)
        self.assertEqual(stat.S_IMODE(self.a.stat().st_mode), 0o640)

    def test_status_tells_original_edited_changed_since_and_missing(self):
        folder = self.save()
        lines = lambda: dict(reversed(l.split(": ", 1)) for l in self.run_main("status", folder)[1].splitlines() if not l.startswith("note:"))  # noqa: E731
        self.assertEqual(set(lines().values()), {"original"})
        self.edit()
        self.assertEqual(lines()[str(self.a)], "changed since")  # not recorded yet
        self.run_main("record", folder)
        self.assertEqual(lines()[str(self.a)], "edited")
        self.assertEqual(lines()[str(self.new)], "edited")
        self.assertEqual(lines()[str(self.b)], "edited")  # deleted by the edit, recorded as such
        self.a.write_text("someone else\n", encoding="utf-8")
        self.new.unlink()
        self.assertEqual(lines()[str(self.a)], "changed since")
        self.assertEqual(lines()[str(self.new)], "original")  # it was absent, it is absent
        self.b.write_text("back with other text\n", encoding="utf-8")
        self.b.unlink()
        self.assertEqual(lines()[str(self.b)], "edited")
        folder2 = self.save(self.a)
        self.a.unlink()
        self.assertEqual(self.run_main("status", folder2)[1].splitlines()[0], f"missing: {self.a}")

    def test_restore_refuses_a_file_changed_since_the_edit_lists_it_and_touches_nothing(self):
        folder = self.save()
        self.edit()
        self.run_main("record", folder)
        self.a.write_text("a later hand edit\n", encoding="utf-8")
        code, out, err = self.run_main("restore", folder)
        self.assertEqual(code, 2)
        self.assertIn(str(self.a), err)
        self.assertNotIn(str(self.b), err)
        self.assertEqual(self.a.read_text(encoding="utf-8"), "a later hand edit\n")
        self.assertFalse(self.b.exists())  # the other files were not restored either
        self.assertTrue(self.new.exists())
        self.assertEqual(out, "")

    def test_force_restores_the_refused_file_too(self):
        folder = self.save()
        self.edit()
        self.run_main("record", folder)
        self.a.write_text("a later hand edit\n", encoding="utf-8")
        code, _, err = self.run_main("restore", folder, "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.a.read_text(encoding="utf-8"), '{"token": "SECRET-A", "model": "opus"}\n')
        self.assertFalse(self.new.exists())

    def test_without_record_an_edited_file_is_refused_until_forced(self):
        folder = self.save()
        self.edit()
        code, _, err = self.run_main("restore", folder)
        self.assertEqual(code, 2)
        self.assertIn(str(self.a), err)
        self.assertEqual(self.run_main("restore", folder, "--force")[0], 0)
        self.assertEqual(self.b.read_text(encoding="utf-8"), "original b\n")

    def test_a_damaged_copy_is_exit_1_and_nothing_is_restored(self):
        folder = self.save()
        self.edit()
        self.run_main("record", folder)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        victim = next(e for e in manifest["files"] if e["path"] == str(self.b))
        (folder / victim["copy"]).write_bytes(b"tampered")
        code, _, err = self.run_main("restore", folder, "--force")
        self.assertEqual(code, 1)
        self.assertIn("does not match", err)
        self.assertEqual(self.a.read_text(encoding="utf-8"), '{"model": "sonnet"}\n')

    def test_a_manifest_that_names_a_copy_outside_files_is_refused(self):
        folder = self.save()
        self.edit()
        self.run_main("record", folder)
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["copy"] = "../manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        code, _, err = self.run_main("restore", folder, "--force")
        self.assertEqual(code, 2)
        self.assertIn("outside files/", err)

    def test_a_folder_without_a_manifest_is_exit_2(self):
        for command in ("record", "status", "restore"):
            code, _, err = self.run_main(command, self.setup)
            self.assertEqual(code, 2, command)
            self.assertIn("not a backup folder", err)

    def test_a_failed_replace_leaves_the_target_as_it_was_and_no_temporary_file(self):
        folder = self.save(self.a)
        self.a.write_text("edited\n", encoding="utf-8")
        self.run_main("record", folder)
        with mock.patch.object(backup.os, "replace", side_effect=PermissionError(13, "denied")):
            code, _, err = self.run_main("restore", folder)
        self.assertEqual(code, 1)
        self.assertEqual(self.a.read_text(encoding="utf-8"), "edited\n")
        self.assertEqual(sorted(p.name for p in self.setup.iterdir() if p.is_file()), ["a.json"])

    def test_restore_writes_beside_the_target_and_replaces_it_atomically(self):
        folder = self.save(self.a)
        self.a.write_text("edited\n", encoding="utf-8")
        self.run_main("record", folder)
        real = os.replace
        seen = []

        def spy(src, dst):
            seen.append((pathlib.Path(src).parent, pathlib.Path(dst)))
            return real(src, dst)

        with mock.patch.object(backup.os, "replace", spy):
            self.assertEqual(self.run_main("restore", folder)[0], 0)
        self.assertIn((self.a.parent, self.a), seen)

    def test_the_command_line_exit_codes(self):
        script = str(ROOT / "scripts" / "backup.py")

        def run(*args):
            return subprocess.run([sys.executable, "-I", script, *map(str, args)], capture_output=True, text=True, encoding="utf-8")

        saved = run("save", "--out", self.store, self.a, self.new)
        self.assertEqual(saved.returncode, 0, saved.stderr)
        folder = re.search(r"^folder: (.+)$", saved.stdout, re.M).group(1)
        self.edit()
        self.assertEqual(run("record", folder).returncode, 0)
        self.assertEqual(run("restore", folder).returncode, 0)
        self.assertEqual(run("status", folder).returncode, 0)
        self.assertEqual(run("restore", self.setup).returncode, 2)
        self.assertEqual(run("save").returncode, 2)
        self.assertEqual(run("--help").returncode, 0)
        self.assertEqual(self.a.read_text(encoding="utf-8"), '{"token": "SECRET-A", "model": "opus"}\n')


if __name__ == "__main__":
    unittest.main()
