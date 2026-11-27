#!/usr/bin/env python3
"""Back up the files an upgrade will edit, and put the originals back if the person wants them back.

Subcommands:
  save --out STORE PATH...   copy each PATH (a file; an absent one is recorded as absent) into a new
                             timestamped folder under STORE, with manifest.json and a copy of this script
                             (backup.py), so the restore does not depend on the plugin staying installed.
                             Prints the backup folder and the command that restores it, quoted for this
                             platform (PowerShell on Windows). Never prints file contents.
  record BACKUP_DIR [PATH...]
                             after an edit: store the sha256 of each named PATH as it is now (the "post-edit"
                             hash); no PATH means every path in the backup. A PATH the backup does not hold is
                             refused. Call it after each edit with that edit's path, so an unrelated change
                             made meanwhile is not adopted as the edit.
  restore BACKUP_DIR [--force]
                             put the originals back; delete the files that did not exist originally
  status BACKUP_DIR          one line per path: original, edited, changed since, or missing

Where the copies go. --out is optional: the default store is ~/.grade-optimizer-backups, a folder in the
user's home that is outside ~/.claude (or $CLAUDE_CONFIG_DIR) and outside any project, so that editing the
setup, cleaning a repository or reinstalling Claude Code does not take the backups with it. Nothing prunes it:
it holds copies of settings files, which can hold secrets, so delete a backup when you no longer need it.

manifest.json (version 1) lists, for each path: `path` (absolute, symlinks resolved), `sha256` of the original
or "absent", `size`, `mode` (octal text; null when absent), `copy` (name under files/; null when absent) and
`post_edit_sha256` (null until `record`; "absent" when the edit deleted the file).

restore rules. Restore is atomic per file, not across files. It first validates every file and refuses
the whole run, touching nothing, when (a) a path no longer resolves to the canonical path recorded at save (a parent
folder was replaced by a symlink or junction since; --force does not override this) or (b) a file is neither the
recorded post-edit content nor already the original (changed since the edit; all are listed; --force restores those
too). A backup that was not `record`ed has no post-edit hash, so only an unchanged-from-original file passes without
--force. The copies' hashes are checked against the manifest before anything is written. Only after that does it
replace the files one by one, each through a temporary file in its own folder and os.replace, so a reader never sees a
half-written file. If one file then fails (a lock, a permission), the others are still restored, each result is
printed (`restored:`, `removed:`, `failed:`) and the exit is 1: the setup can be half restored. Running restore
again finishes it, because a file already original is skipped and a pending one still matches its post-edit hash.
POSIX modes are put back; on Windows only the content is.

Privacy. The store folder, each backup folder, the copies and manifest.json are created readable by the current
user only where the system has modes (POSIX 0700 for folders, 0600 for files). On Windows the standard library
cannot set access rules: folders and files take the ACL they inherit, so keep the store somewhere only you can
read (the default, under your user profile, normally is). A store that already exists is not changed, only
warned about when it is open to others. Files larger than memory are not supported.

Exit codes:
  0  done (status always exits 0; restore with nothing to do exits 0)
  1  an I/O error, or a backup copy that does not match its recorded hash (nothing was restored from it); for
     restore, at least one file could not be replaced (the others were; run it again to finish)
  2  the command line or the backup cannot be used: bad flag, not a backup folder, a PATH that is a folder or that
     the backup does not hold, or restore refused (a path redirected since the backup, or files changed since the
     edit: listed, --force overrides only the second)

Stdlib only. Python 3.9+. No network.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import shlex
import stat
import sys
import tempfile

HAS_MODES = hasattr(os, "fchmod")  # POSIX modes; on Windows the folder's ACL decides who can read
MANIFEST = "manifest.json"
VERSION = 1
DEFAULT_STORE = pathlib.Path.home() / ".grade-optimizer-backups"
ABSENT = "absent"
NOT_A_FILE = "not-a-file"


class Refused(Exception):
    """The command line or the backup cannot be used. main() prints the message and exits 2."""


class Failed(Exception):
    """An I/O error or a damaged copy. main() prints the message and exits 1."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current(path: pathlib.Path) -> str:
    """sha256 of the file at path, ABSENT when there is nothing, NOT_A_FILE for a folder or other entry."""
    try:
        if not os.path.lexists(path):
            return ABSENT
        if not path.is_file():
            return NOT_A_FILE
        return sha256(path.read_bytes())
    except OSError as exc:
        raise Failed(f"cannot read {path}: {type(exc).__name__}: {exc.strerror or exc}") from exc


def write_private(path: pathlib.Path, data: bytes) -> None:
    """Create path (it must not exist) readable by the current user only where the system has modes."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def replace_atomic(target: pathlib.Path, data: bytes, mode=None) -> None:
    """Write data beside target in a temporary file, then os.replace it over target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None and HAS_MODES:
            os.chmod(tmp, mode)
        os.replace(tmp, str(target))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_manifest(folder: pathlib.Path, manifest: dict) -> None:
    replace_atomic(folder / MANIFEST, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"), 0o600)


def load(folder_arg: str):
    folder = pathlib.Path(folder_arg).expanduser().resolve()
    path = folder / MANIFEST
    if not path.is_file():
        raise Refused(f"{folder} is not a backup folder: no {MANIFEST} in it")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        files = manifest["files"]
        if manifest.get("version") != VERSION or not isinstance(files, list):
            raise ValueError("unknown manifest version")
        for entry in files:
            if not isinstance(entry["path"], str) or not isinstance(entry["sha256"], str):
                raise ValueError("an entry has no path or hash")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refused(f"{path} cannot be read as a version {VERSION} manifest ({type(exc).__name__}: {exc})") from exc
    return folder, manifest


def copy_path(folder: pathlib.Path, entry: dict) -> pathlib.Path:
    """The stored copy of an entry; refuses a name that would leave the files/ folder."""
    name = entry.get("copy")
    if not isinstance(name, str) or pathlib.PurePath(name).parts[:1] != ("files",) or ".." in pathlib.PurePath(name).parts:
        raise Refused(f"the manifest names a copy outside files/ for {entry['path']}")
    return folder / name


def canonical(path) -> str:
    return os.path.normcase(os.path.realpath(path))


def redirected(entry: dict) -> bool:
    """True when the recorded path no longer resolves to itself (a parent folder or the file became a link)."""
    return canonical(entry["path"]) != os.path.normcase(entry["path"])


def restore_command(folder: pathlib.Path, windows=None) -> str:
    """The command that restores `folder` with the copy of this script stored in it, quoted for the platform:
    PowerShell on Windows (& 'program' 'script' restore 'folder'), a POSIX shell elsewhere."""
    argv = [sys.executable or "python", str(folder / "backup.py"), "restore", str(folder)]
    if os.name == "nt" if windows is None else windows:
        return "& " + " ".join("'" + a.replace("'", "''") + "'" for a in argv)
    return " ".join(shlex.quote(a) for a in argv)


# ---------------------------------------------------------------- save

def open_store(store: pathlib.Path) -> None:
    """Create the store owner-only; an existing one is left as it is (warned about when open to others)."""
    if store.exists():
        if not store.is_dir():
            raise Refused(f"the store {store} exists and is not a folder")
        if HAS_MODES and stat.S_IMODE(store.stat().st_mode) & 0o077:
            print(f"backup.py: warning: {store} is readable by others; the backups in it can hold secrets. "
                  f"Consider chmod 700 {store}", file=sys.stderr)
    else:
        store.mkdir(parents=True, mode=0o700)
        if HAS_MODES:
            os.chmod(store, 0o700)
    config = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude").resolve()
    real = store.resolve()
    if real == config or config in real.parents:
        print(f"backup.py: warning: the store is inside {config}; changes to the setup can reach it. "
              "Prefer a folder outside it", file=sys.stderr)
    if os.name == "nt":
        home = pathlib.Path.home().resolve()
        if not (real == home or home in real.parents):
            print("backup.py: note: on Windows the store takes the access rules of its folder, and this one is outside "
                  "your user profile; make sure only you can read it", file=sys.stderr)


def new_backup_dir(store: pathlib.Path) -> pathlib.Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(100):
        folder = store / f"{stamp}-{os.urandom(2).hex()}"
        try:
            folder.mkdir(mode=0o700)
        except FileExistsError:
            continue
        if HAS_MODES:
            os.chmod(folder, 0o700)
        (folder / "files").mkdir(mode=0o700)
        if HAS_MODES:
            os.chmod(folder / "files", 0o700)
        return folder
    raise Failed(f"could not create a new backup folder under {store}")


def cmd_save(args) -> int:
    targets, seen = [], set()
    for raw in args.paths:
        path = pathlib.Path(raw).expanduser().resolve()
        if path.is_dir():
            raise Refused(f"{path} is a folder: name the files to back up")
        if os.path.normcase(str(path)) not in seen:
            seen.add(os.path.normcase(str(path)))
            targets.append(path)
    # read everything before creating anything, so a failure leaves no half backup
    captured = []
    for path in targets:
        try:
            if path.exists():
                data = path.read_bytes()
                st = path.stat()
                captured.append((path, data, st.st_size, stat.S_IMODE(st.st_mode)))
            else:
                captured.append((path, None, None, None))
        except OSError as exc:
            raise Failed(f"cannot read {path}: {type(exc).__name__}: {exc.strerror or exc}") from exc
    store = pathlib.Path(args.out).expanduser() if args.out else DEFAULT_STORE
    try:
        open_store(store)
        folder = new_backup_dir(store.resolve())
        entries = []
        for i, (path, data, size, mode) in enumerate(captured):
            if data is None:
                entries.append({"path": str(path), "sha256": ABSENT, "size": None, "mode": None, "copy": None, "post_edit_sha256": None})
                continue
            name = f"files/{i:03d}-{path.name}"
            write_private(folder / name, data)
            entries.append({"path": str(path), "sha256": sha256(data), "size": size, "mode": f"{mode:04o}", "copy": name,
                            "post_edit_sha256": None})
        write_private(folder / "backup.py", pathlib.Path(__file__).read_bytes())
        save_manifest(folder, {"version": VERSION, "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                               "id": folder.name, "files": entries})
    except OSError as exc:
        raise Failed(f"could not write the backup: {type(exc).__name__}: {exc.strerror or exc}") from exc
    kept = sum(1 for e in entries if e["copy"])
    print(f"backup: {folder.name}")
    print(f"folder: {folder}")
    print(f"saved {kept} file(s), {len(entries) - kept} recorded as absent")
    print(f"restore with: {restore_command(folder)}")
    return 0


# ---------------------------------------------------------------- record, status, restore

def cmd_record(args) -> int:
    folder, manifest = load(args.backup)
    if args.paths:
        wanted = {canonical(pathlib.Path(p).expanduser()) for p in args.paths}
        held = {canonical(e["path"]) for e in manifest["files"]}
        unknown = sorted(wanted - held)
        if unknown:
            raise Refused("the backup does not hold: " + ", ".join(unknown) + "; nothing was recorded")
        chosen = [e for e in manifest["files"] if canonical(e["path"]) in wanted]
    else:
        chosen = manifest["files"]
    for entry in chosen:
        entry["post_edit_sha256"] = current(pathlib.Path(entry["path"]))
    try:
        save_manifest(folder, manifest)
    except OSError as exc:
        raise Failed(f"could not update {folder / MANIFEST}: {type(exc).__name__}: {exc.strerror or exc}") from exc
    for entry in chosen:
        print(f"{'changed' if entry['post_edit_sha256'] != entry['sha256'] else 'same as original'}: {entry['path']}")
    return 0


def state(entry: dict) -> str:
    """original / edited / changed since / missing, for one manifest entry against the disk now."""
    now = current(pathlib.Path(entry["path"]))
    if now == entry["sha256"]:
        return "original"
    if entry.get("post_edit_sha256") is not None and now == entry["post_edit_sha256"]:
        return "edited"
    if now == ABSENT:
        return "missing"
    return "changed since"


def cmd_status(args) -> int:
    _, manifest = load(args.backup)
    for entry in manifest["files"]:
        print(f"{state(entry)}: {entry['path']}")
    if all(e.get("post_edit_sha256") is None for e in manifest["files"]):
        print("note: `record` has not been run on this backup, so an edited file shows as changed since")
    return 0


def put_back(entry: dict, data) -> str:
    """Restore one file; returns the line to print. Raises OSError or Failed on failure."""
    path = pathlib.Path(entry["path"])
    if redirected(entry):
        raise Failed("it no longer resolves to the path recorded in the backup")
    if data is None:
        if path.is_dir() and not path.is_symlink():
            raise Failed("it is a folder now; it was not removed")
        path.unlink()
        return f"removed (did not exist originally): {path}"
    mode = int(entry["mode"], 8) if isinstance(entry.get("mode"), str) else None
    replace_atomic(path, data, mode)
    return f"restored: {path}"


def cmd_restore(args) -> int:
    folder, manifest = load(args.backup)
    entries = manifest["files"]
    moved = [e["path"] for e in entries if redirected(e)]
    if moved:
        print("restore refused: these paths no longer resolve to the path recorded in the backup (a parent folder or "
              "the file became a symlink or junction). --force does not override this. Nothing was touched:", file=sys.stderr)
        for path in moved:
            print(f"  {path}", file=sys.stderr)
        return 2
    states = [state(e) for e in entries]
    # "missing" is a path now absent whose original was present and whose deletion was not recorded as the edit
    refused = [e["path"] for e, s in zip(entries, states) if s in ("changed since", "missing")]
    if refused and not args.force:
        print("restore refused: these files are neither the original nor the recorded post-edit content "
              "(changed since the edit, or never recorded). Nothing was touched:", file=sys.stderr)
        for path in refused:
            print(f"  {path}", file=sys.stderr)
        print("Review them, then run again with --force to overwrite them anyway.", file=sys.stderr)
        return 2
    plan = []
    for entry, s in zip(entries, states):
        if s == "original":
            continue
        if entry["sha256"] == ABSENT:
            plan.append((entry, None))
            continue
        copy = copy_path(folder, entry)
        try:
            data = copy.read_bytes()
        except OSError as exc:
            raise Failed(f"cannot read the backup copy {copy}: {type(exc).__name__}: {exc.strerror or exc}") from exc
        if sha256(data) != entry["sha256"]:
            raise Failed(f"the backup copy {copy} does not match its recorded hash; nothing was restored")
        plan.append((entry, data))
    if not plan:
        print("nothing to restore: every file is already the original")
        return 0
    failed = 0
    for entry, data in plan:  # one file at a time: a failure on one does not stop the others
        try:
            print(put_back(entry, data))
        except (OSError, Failed) as exc:
            failed += 1
            reason = f"{type(exc).__name__}: {exc.strerror or exc}" if isinstance(exc, OSError) else str(exc)
            print(f"failed: {entry['path']} ({reason})")
    if failed:
        print(f"backup.py: {failed} of {len(plan)} file(s) could not be restored; the others were. "
              "Fix the cause and run the same restore again to finish", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- command line

def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="backup.py", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Exit codes: 0 done, 1 I/O error or damaged copy, 2 unusable input or restore refused.")
    sub = ap.add_subparsers(dest="command", required=True)
    save = sub.add_parser("save", help="copy files into a new timestamped backup")
    save.add_argument("--out", default=None, metavar="STORE", help="store folder (default: ~/.grade-optimizer-backups)")
    save.add_argument("paths", nargs="+", metavar="PATH", help="files to back up; an absent one is recorded as absent")
    rec = sub.add_parser("record", help="store the post-edit hash of the named paths, or of all (run after an edit)")
    rec.add_argument("backup", metavar="BACKUP_DIR")
    rec.add_argument("paths", nargs="*", metavar="PATH", help="only these paths (default: every path in the backup)")
    res = sub.add_parser("restore", help="put the originals back")
    res.add_argument("backup", metavar="BACKUP_DIR")
    res.add_argument("--force", action="store_true", help="also overwrite files changed since the edit")
    st = sub.add_parser("status", help="per path: original, edited, changed since, missing")
    st.add_argument("backup", metavar="BACKUP_DIR")
    return ap


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    handler = {"save": cmd_save, "record": cmd_record, "restore": cmd_restore, "status": cmd_status}[args.command]
    try:
        return handler(args)
    except Refused as exc:
        print(f"backup.py: {exc}", file=sys.stderr)
        return 2
    except Failed as exc:
        print(f"backup.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
