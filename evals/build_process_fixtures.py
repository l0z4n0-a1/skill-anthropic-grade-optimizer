#!/usr/bin/env python3
"""Build two throwaway orchestration processes for calibrating the process review.

`process-planted/` has ten defects, each documented in ANSWER-KEY.md, and four things
that are deliberately sound. `process-clean/` is the same kind of process built to give
a reviewer nothing to find that is a defect by the guide's standard. It is not proven
defect-free: ANSWER-KEY.md records its residues and one open finding (some tickets' C2
states something a script could decide, and the `fields` check looks only at presence and
placeholders). A review that names that finding is right and must not be scored as a false
one. Each holds a small process ("docket": a runner, checks, a release step, a gate) and
the records of past runs: records/ledger.jsonl and, for the later runs, records/verdicts/.
The planted process has three checks (schema, refs, accept); the clean one has five (those
and fields, scope). The records come from a seeded generator, so every count in the answer
key is exact and the generated files are identical on every run.

`pack_sha` in the clean ledger is fixture metadata: the generator hashes a synthetic
label (`<run>:pack`), not the bytes of a pack. It is a stand-in for the digest the clean
runner would record, and it is not a verified pack digest.

Usage: build_process_fixtures.py <output dir>
Writes <output dir>/process-planted and <output dir>/process-clean. Nothing here is
executed by the review; the runners are written to be runnable, with the executor and the
reviewers supplied as commands through the environment.
Use a new, empty output directory: the named folders are overwritten file by file, and a
file left from an earlier build that this one does not write stays in place. Writing needs
a folder that can be created; a failed write raises and exits 1 with a traceback.
Exit: 0 when both folders were built; 2 when the arguments are not exactly one directory
(a flag such as --help also gives 2 and prints this text to stderr).
"""
import datetime as dt
import hashlib
import json
import pathlib
import random
import sys

SEED = 20261127
CUT = 20  # runs before this index have a ledger row but no verdict files
CAP = 250_000


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Files that carry the process
# ---------------------------------------------------------------------------

RUN_PLANTED = r'''#!/usr/bin/env python3
"""Run one ticket through the executor and the reviewers.

Usage: run.py <ticket-id>
In:    tickets/<ticket-id>.json; DOCKET_EXECUTOR, DOCKET_REVIEWER and DOCKET_SECOND name the commands.
Out:   work/<run>/, records/verdicts/<run>-r<n>.md, one row appended to records/ledger.jsonl.
Exit:  0 when the run closed, 1 otherwise.
"""
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
RECORDS = ROOT / "records"
MAX_ROUNDS = 4
EXECUTOR = os.environ.get("DOCKET_EXECUTOR", "docket-exec").split()
PRIMARY = os.environ.get("DOCKET_REVIEWER", "docket-review").split()
SECOND = os.environ.get("DOCKET_SECOND", "docket-review-x").split()


def read(path):
    return path.read_text(encoding="utf-8")


def call(cmd, text, cwd):
    proc = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=1800)
    used = re.findall(r"^TOKENS: (\d+)$", proc.stdout, re.M)
    return proc.returncode, proc.stdout, int(used[-1]) if used else 0


def compose(ticket_id, workdir):
    ticket = json.loads(read(ROOT / "tickets" / f"{ticket_id}.json"))
    contract = {"ticket": ticket_id, "goal": ticket["goal"], "criteria": ticket["criteria"], "checks": ticket["checks"]}
    path = workdir / "contract.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return path


def snapshot(workdir):
    return {p.relative_to(workdir).as_posix(): p.stat().st_mtime_ns for p in workdir.rglob("*") if p.is_file()}


def deliverable(workdir):
    parts = []
    for p in sorted(workdir.rglob("*")):
        name = p.relative_to(workdir).as_posix()
        if p.is_file() and p.suffix in (".json", ".py", ".md") and name not in ("contract.json", "report.md"):
            parts.append(f"=== {name} ===\n{read(p)[:6000]}")
    return "\n".join(parts)


def run_checks(contract, workdir):
    results, lines = {}, []
    for entry in contract["checks"]:
        script = ROOT / "checks" / f"{entry['name']}.py"
        proc = subprocess.run([sys.executable, str(script), str(workdir)] + entry.get("args", []),
                              capture_output=True, text=True, encoding="utf-8", timeout=300)
        results[entry["name"]] = "pass" if proc.returncode == 0 else "fail"
        lines.append(f"{entry['name']}: exit {proc.returncode}\n{(proc.stdout + proc.stderr).strip()[-400:]}")
    return results, "\n".join(lines)


def review(cmd, contract, workdir):
    report = workdir / "report.md"
    prompt = read(ROOT / "prompts" / "review.md")
    prompt += "\n## Contract\n" + json.dumps(contract, indent=2)
    prompt += "\n## Executor report\n" + (read(report) if report.exists() else "(none)")
    prompt += "\n## Work\n" + deliverable(workdir)
    code, text, used = call(cmd, prompt, workdir)
    verdict = re.search(r"^VERDICT: (PASS|FAIL|ESCALATE)", text, re.M)
    listed = re.search(r"^FAILED:(.*)$", text, re.M)
    ids = sorted(i.strip() for i in listed.group(1).split(",") if i.strip()) if listed else []
    return (verdict.group(1).lower() if verdict and code == 0 else "fail"), ids, text, used


def main(ticket_id):
    started = dt.datetime.now(dt.timezone.utc)
    run = "r" + started.strftime("%Y%m%d%H%M%S")
    workdir = WORK / run
    workdir.mkdir(parents=True)
    (RECORDS / "verdicts").mkdir(parents=True, exist_ok=True)
    contract_path = compose(ticket_id, workdir)
    rounds, tokens, previous, feedback, lesson, ended = [], 0, None, "", "", "limit"
    for n in range(1, MAX_ROUNDS + 1):
        before = snapshot(workdir)
        prompt = read(ROOT / "prompts" / "execute.md") + f"\nContract: {contract_path}\n{feedback}"
        code, _, used = call(EXECUTOR, prompt, workdir)
        tokens += used
        if code != 0:
            ended = "dead"
            break
        after = snapshot(workdir)
        touched = sorted(k for k in after if k != "report.md" and before.get(k) != after[k])
        contract = json.loads(read(contract_path))
        checks, check_text = run_checks(contract, workdir)
        verdict, ids, text, used = review(PRIMARY, contract, workdir)
        tokens += used
        lesson = (re.findall(r"^LESSON: (.*)$", text, re.M) or [""])[-1]
        second, second_text = None, ""
        if verdict == "pass" and "fail" not in checks.values():
            second, more, second_text, used = review(SECOND, contract, workdir)
            tokens += used
            ids += more
        failed = sorted(set(ids) | {e["criterion"] for e in contract["checks"] if checks[e["name"]] == "fail"})
        path = RECORDS / "verdicts" / f"{run}-r{n}.md"
        path.write_text(f"## checks\n{check_text}\n\n## primary\n{text}\n\n## second\n{second_text or '(not run)'}\n",
                        encoding="utf-8")
        rounds.append({"n": n, "touched": touched, "checks": checks, "primary": verdict, "second": second,
                       "failed": failed})
        if verdict == "escalate":
            ended = "escalated"
            break
        if not failed and verdict == "pass" and second != "fail":
            ended = "closed"
            break
        if failed == previous:
            ended = "stalled"
            break
        previous = failed
        feedback = "Rejected last round:\n" + read(path)
    row = {"run": run, "ticket": ticket_id, "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "outcome": ended,
           "rounds": rounds, "tokens": tokens, "seconds": int(time.time() - started.timestamp()),
           "status": "ok",
           "lesson": lesson}
    with (RECORDS / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return 0 if ended == "closed" else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
'''

RUN_CLEAN = r'''#!/usr/bin/env python3
"""Run one ticket through the executor and the reviewer.

Usage: run.py <ticket-id>
In:    tickets/<ticket-id>.json, pack/ and tests/; DOCKET_EXECUTOR and DOCKET_REVIEWER name the commands.
Out:   contracts/<run>.json (read-only), baselines/<run>/ (the input pack/ and tests/, outside the workspace),
       work/<run>/, reviews/<run>/ (pack/ and tests/ as the reviewer reads them),
       records/verdicts/<run>-r<n>.md, one row appended to records/ledger.jsonl (tokens per run, and per round
       what the executor and the reviewer each spent; a dead run has the exit code and stderr in `reason`).
Exit:  0 when the run closed, 1 otherwise.
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
CONTRACTS = ROOT / "contracts"
BASELINES = ROOT / "baselines"
REVIEWS = ROOT / "reviews"
RECORDS = ROOT / "records"
MAX_ROUNDS = 3
TOKEN_CAP = 250_000
EXECUTOR = os.environ.get("DOCKET_EXECUTOR", "docket-exec").split()
REVIEWER = os.environ.get("DOCKET_REVIEWER", "docket-review").split()
VAGUE = ("reasonable", "carefully", "appropriate", "properly")


def read(path):
    return path.read_text(encoding="utf-8")


def call(cmd, text, cwd):
    try:
        proc = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=1800)
    except subprocess.TimeoutExpired:
        return 124, "", 0, "no answer within 1800 s"
    used = re.findall(r"^TOKENS: (\d+)$", proc.stdout, re.M)
    return proc.returncode, proc.stdout, int(used[-1]) if used else 0, proc.stderr


def compose(ticket_id, run):
    ticket = json.loads(read(ROOT / "tickets" / f"{ticket_id}.json"))
    contract = {"ticket": ticket_id, "goal": ticket["goal"], "criteria": ticket["criteria"], "checks": ticket["checks"]}
    CONTRACTS.mkdir(exist_ok=True)
    path = CONTRACTS / f"{run}.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    path.chmod(0o444)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, sha):
    data = path.read_bytes()
    return json.loads(data.decode("utf-8")) if hashlib.sha256(data).hexdigest() == sha else None


def lint(contract, known):
    """What a script can tell about a contract before an executor is paid: a criterion that names an
    activity, or a pack file that does not exist."""
    problems = []
    for c in contract["criteria"]:
        for word in VAGUE:
            if word in c["text"].lower():
                problems.append(f"{c['id']}: '{word}' describes an activity, not a state of the work")
        for name in re.findall(r"pack/[\w.-]+\.json", c["text"]):
            if name not in known:
                problems.append(f"{c['id']}: {name} is not in the pack")
    return problems


def stage(run, workdir):
    """The executor gets copies of pack/ and tests/; the input pack and tests are kept outside its workspace."""
    for part in ("pack", "tests"):
        if (ROOT / part).is_dir():
            shutil.copytree(ROOT / part, workdir / part)
            shutil.copytree(ROOT / part, BASELINES / run / part)
    return BASELINES / run


def snapshot(workdir):
    return {p.relative_to(workdir).as_posix(): p.stat().st_mtime_ns for p in workdir.rglob("*") if p.is_file()}


def run_checks(contract, workdir, baseline):
    results, lines, red = {}, [], {}
    env = dict(os.environ, DOCKET_BASELINE=str(baseline))
    for entry in contract["checks"]:
        script = ROOT / "checks" / f"{entry['name']}.py"
        try:
            proc = subprocess.run([sys.executable, str(script), str(workdir)] + entry.get("args", []),
                                  capture_output=True, text=True, encoding="utf-8", timeout=300, env=env)
            code, out = proc.returncode, (proc.stdout + proc.stderr).strip()[-400:]
        except subprocess.TimeoutExpired:
            code, out = 124, "no answer within 300 s"
        results[entry["name"]] = "pass" if code == 0 else "fail"
        lines.append(f"{entry['name']}: exit {code}\n{out}")
        if code != 0:
            red[entry["name"]] = out
    return results, "\n".join(lines), red


def review(contract, workdir, run):
    """The reviewer reads pack/ and tests/ from a copy, so it never sees the executor's own files."""
    seen = REVIEWS / run
    shutil.rmtree(seen, ignore_errors=True)
    for part in ("pack", "tests"):
        if (workdir / part).is_dir():
            shutil.copytree(workdir / part, seen / part)
    seen.mkdir(parents=True, exist_ok=True)
    prompt = read(ROOT / "prompts" / "review.md")
    prompt += "\n## Contract\n" + json.dumps(contract, indent=2)
    prompt += "\n## Work\nThe work is in the current directory: `pack/` holds the data and `tests/` the unit tests.\n"
    code, text, used, _ = call(REVIEWER, prompt, seen)
    verdict = re.search(r"^VERDICT: (PASS|FAIL|ESCALATE)", text, re.M)
    listed = re.search(r"^FAILED:(.*)$", text, re.M)
    ids = sorted(i.strip() for i in listed.group(1).split(",") if i.strip()) if listed else []
    if code != 0 or not verdict:
        return "error", [], text, used
    return verdict.group(1).lower(), ids, text, used


def shape(line):
    return re.sub(r"[a-z]-\d+|'[^']*'|\d+", "#", " ".join(line.lower().split()))


def count(line):
    found = re.findall(r"\d+", re.sub(r"[a-z]-\d+|'[^']*'", "", line))
    return int(found[0]) if found else 1


def signature(verdict, text, red):
    """What a round says is wrong: each finding with ids, numbers and quoted values blanked out,
    and the number of offenders it names."""
    items = re.findall(r"^(C\d+): (.*)$", text, re.M) if verdict == "fail" else []
    for name, output in red.items():
        items += [(name, line) for line in output.splitlines() if line.strip()]
    return frozenset((i, shape(t)) for i, t in items), sum(count(t) for _, t in items)


def stalled(previous, current):
    """The same findings again, with no fewer offenders than the round before."""
    return previous is not None and previous[0] == current[0] and current[1] >= previous[1]


def main(ticket_id):
    from ledger import digest
    started = dt.datetime.now(dt.timezone.utc)
    run = "r" + started.strftime("%Y%m%d%H%M%S")
    workdir = WORK / run
    workdir.mkdir(parents=True)
    (RECORDS / "verdicts").mkdir(parents=True, exist_ok=True)
    contract_path, sha = compose(ticket_id, run)
    contract = load(contract_path, sha)
    problems = lint(contract, {f"pack/{p.name}" for p in (ROOT / "pack").glob("*.json")})
    rounds, tokens, previous, feedback, ended, reason, pack, sealed = [], 0, None, "", "limit", "", "", None
    if problems:
        ended, reason = "escalated", "contract lint: " + "; ".join(problems)
    else:
        baseline = stage(run, workdir)
        sealed = (digest(baseline), digest(ROOT / "checks"))
    for n in range(1, MAX_ROUNDS + 1):
        if problems:
            break
        before = snapshot(workdir)
        prompt = read(ROOT / "prompts" / "execute.md") + "\n## Contract\n" + json.dumps(contract, indent=2) + f"\n{feedback}"
        code, _, used, err = call(EXECUTOR, prompt, workdir)
        tokens += used
        spent, judged = used, 0
        if code != 0:
            ended, reason = "dead", f"executor exited {code}: " + " ".join(err.split())[-300:]
            break
        contract = load(contract_path, sha)
        if contract is None:
            ended, reason = "escalated", "the contract file changed during the run"
            break
        if (digest(baseline), digest(ROOT / "checks")) != sealed:
            ended, reason = "escalated", "the baseline or the checks changed during the run"
            break
        after = snapshot(workdir)
        touched = sorted(k for k in after if k != "report.md" and before.get(k) != after[k])
        path = RECORDS / "verdicts" / f"{run}-r{n}.md"
        report = read(workdir / "report.md") if (workdir / "report.md").exists() else ""
        if report.startswith("BLOCKED:"):
            blocked = report.splitlines()[0]
            path.write_text(f"## executor\n{blocked}\n", encoding="utf-8")
            rounds.append({"n": n, "touched": touched, "checks": {}, "verdict": "blocked", "failed": [],
                           "exec_tokens": spent, "review_tokens": 0})
            ended, reason = "escalated", "executor " + blocked
            break
        pack = digest(workdir / "pack")
        checks, check_text, red = run_checks(contract, workdir, baseline)
        if red:
            verdict, ids, text = "skipped", [], "(not run: a check is red)\n"
        else:
            verdict, ids, text, used = review(contract, workdir, run)
            tokens, judged = tokens + used, used
            if verdict == "error":
                verdict, ids, text, used = review(contract, workdir, run)
                tokens, judged = tokens + used, judged + used
        failed = sorted(set(ids) | {e["criterion"] for e in contract["checks"] if checks[e["name"]] == "fail"})
        path.write_text(f"## checks\n{check_text}\n\n## review\n{text}", encoding="utf-8")
        rounds.append({"n": n, "touched": touched, "checks": checks, "verdict": verdict, "failed": failed,
                       "exec_tokens": spent, "review_tokens": judged})
        if verdict == "error":
            ended, reason = "error", "the reviewer gave no verdict twice"
            break
        if verdict == "escalate":
            ended, reason = "escalated", "reviewer: ESCALATE " + ", ".join(ids)
            break
        if not failed and verdict == "pass":
            ended = "closed"
            break
        current = signature(verdict, text, red)
        if stalled(previous, current):
            ended = "stalled"
            break
        if tokens >= TOKEN_CAP:
            ended = "limit"
            break
        previous = current
        feedback = "Rejected last round:\n" + read(path)
    row = {"run": run, "ticket": ticket_id, "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "outcome": ended,
           "contract_sha": sha}
    if ended == "closed":
        row["pack_sha"] = pack
    if reason:
        row["reason"] = reason
    row.update({"rounds": rounds, "tokens": tokens, "seconds": int(time.time() - started.timestamp())})
    with (RECORDS / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return 0 if ended == "closed" else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
'''

RELEASE_PY = r'''#!/usr/bin/env python3
"""Publish a closed run's pack to the mirror.

Usage: release.py <run>
In:    work/<run>/pack/; the gate in hooks/gate_release.py.
Out:   mirror/incoming/<run>/ and mirror/current, which names the live version and is replaced atomically.
Exit:  0 when the pointer flipped, 1 when a step failed (no later step runs), 2 when the gate refused.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIRROR = ROOT / "mirror"
POINTER = MIRROR / "current"


def manifest(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def live():
    return POINTER.read_text(encoding="utf-8").strip() if POINTER.exists() else ""


def freeze(ctx):
    for p in ctx["src"].rglob("*"):
        if p.is_file():
            p.chmod(0o444)


def build_manifest(ctx):
    ctx["local"] = manifest(ctx["src"])


def upload(ctx):
    """Copy under a partial name and rename into place, so that a stopped upload leaves nothing under the
    run's name; a copy left by an earlier attempt that never flipped is replaced."""
    if live() == ctx["run"]:
        raise RuntimeError("this run is already the live version")
    part = ctx["dst"].with_name(ctx["dst"].name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    shutil.rmtree(ctx["dst"], ignore_errors=True)
    shutil.copytree(ctx["src"], part, copy_function=shutil.copyfile)
    os.replace(part, ctx["dst"])


def verify(ctx):
    if manifest(ctx["dst"]) != ctx["local"]:
        raise RuntimeError("the uploaded copy differs from the local manifest")


def flip(ctx):
    ctx["previous"] = live()
    tmp = POINTER.with_name("current.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(ctx["run"] + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, POINTER)


def prune(ctx):
    if ctx["previous"] and ctx["previous"] != ctx["run"]:
        shutil.rmtree(MIRROR / "incoming" / ctx["previous"], ignore_errors=True)


STEPS = [("freeze", freeze), ("manifest", build_manifest), ("upload", upload),
         ("verify", verify), ("flip", flip), ("prune", prune)]


def main(run):
    gate = subprocess.run([sys.executable, str(ROOT / "hooks" / "gate_release.py"), run])
    if gate.returncode != 0:
        return 2
    ctx = {"run": run, "src": ROOT / "work" / run / "pack", "dst": MIRROR / "incoming" / run}
    for name, step in STEPS:
        try:
            step(ctx)
        except Exception as exc:
            print(f"release stopped at {name}: {exc}", file=sys.stderr)
            return 1
    print(f"released {run}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
'''

RELEASE_CLEAN = r'''#!/usr/bin/env python3
"""Publish a closed run's pack to the mirror.

Usage: release.py <run>
In:    work/<run>/pack/, which must hash to the ledger's `pack_sha`; the gate in hooks/gate_release.py.
Out:   mirror/incoming/<run>/ and mirror/current, which names the live version and is replaced atomically.
Exit:  0 when the pointer flipped, 1 when a step failed (no later step runs), 2 when the gate refused.
"""
import os
import pathlib
import shutil
import subprocess
import sys

from ledger import manifest, row, seal

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIRROR = ROOT / "mirror"
POINTER = MIRROR / "current"


def live():
    return POINTER.read_text(encoding="utf-8").strip() if POINTER.exists() else ""


def freeze(ctx):
    for p in ctx["src"].rglob("*"):
        if p.is_file():
            p.chmod(0o444)


def build_manifest(ctx):
    ctx["local"] = manifest(ctx["src"])
    if seal(ctx["local"]) != row(ctx["run"])["pack_sha"]:
        raise RuntimeError("the pack is not the one the ledger says was reviewed")


def upload(ctx):
    """Copy under a partial name and rename into place, so that a stopped upload leaves nothing under the
    run's name; a copy left by an earlier attempt that never flipped is replaced."""
    if live() == ctx["run"]:
        raise RuntimeError("this run is already the live version")
    part = ctx["dst"].with_name(ctx["dst"].name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    shutil.rmtree(ctx["dst"], ignore_errors=True)
    shutil.copytree(ctx["src"], part, copy_function=shutil.copyfile)
    os.replace(part, ctx["dst"])


def verify(ctx):
    if manifest(ctx["dst"]) != ctx["local"]:
        raise RuntimeError("the uploaded copy differs from the local manifest")


def flip(ctx):
    ctx["previous"] = live()
    tmp = POINTER.with_name("current.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(ctx["run"] + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, POINTER)


def prune(ctx):
    if ctx["previous"] and ctx["previous"] != ctx["run"]:
        shutil.rmtree(MIRROR / "incoming" / ctx["previous"], ignore_errors=True)


STEPS = [("freeze", freeze), ("manifest", build_manifest), ("upload", upload),
         ("verify", verify), ("flip", flip), ("prune", prune)]


def main(run):
    gate = subprocess.run([sys.executable, str(ROOT / "hooks" / "gate_release.py"), run])
    if gate.returncode != 0:
        return 2
    ctx = {"run": run, "src": ROOT / "work" / run / "pack", "dst": MIRROR / "incoming" / run}
    for name, step in STEPS:
        try:
            step(ctx)
        except Exception as exc:
            print(f"release stopped at {name}: {exc}", file=sys.stderr)
            return 1
    print(f"released {run}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
'''

PRECHECK_PLANTED = r'''#!/usr/bin/env python3
"""Release precheck: the run must have closed.

Usage: precheck.py <run>
Exit:  0 when the run's ledger row says closed, 2 otherwise.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
lines = (ROOT / "records" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
row = next((r for r in map(json.loads, filter(None, lines)) if r["run"] == sys.argv[1]), None)
if row is None or row["outcome"] != "closed":
    print(f"run {sys.argv[1]} has not closed")
    sys.exit(2)
sys.exit(0)
'''

PRECHECK_CLEAN = r'''#!/usr/bin/env python3
"""Release precheck: the run must have closed, and the contract and the pack must be the ones that were judged.

Usage: precheck.py <run>
Exit:  0 when the run's ledger row says closed, contracts/<run>.json matches `contract_sha` and
       work/<run>/pack hashes to `pack_sha`; 2 otherwise.
"""
import hashlib
import pathlib
import sys

from ledger import digest, row

ROOT = pathlib.Path(__file__).resolve().parent.parent
run = sys.argv[1]
recorded = row(run)
if recorded is None or recorded["outcome"] != "closed":
    print(f"run {run} has not closed")
    sys.exit(2)
contract = ROOT / "contracts" / f"{run}.json"
if not contract.exists() or hashlib.sha256(contract.read_bytes()).hexdigest() != recorded["contract_sha"]:
    print(f"contract of {run} does not match the ledger")
    sys.exit(2)
pack = ROOT / "work" / run / "pack"
if not pack.is_dir() or digest(pack) != recorded.get("pack_sha"):
    print(f"the pack of {run} is not the one that was reviewed")
    sys.exit(2)
sys.exit(0)
'''

LEDGER_PY = r'''#!/usr/bin/env python3
"""Shared by run.py, precheck.py and release.py: the ledger row of a run, and the hash of a pack.

row(run)       the run's row in records/ledger.jsonl, or None
manifest(dir)  {relative path: sha256} for every file under dir
seal(m)        one sha256 over a manifest
digest(dir)    seal(manifest(dir)): the value stored as `pack_sha`
"""
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def row(run):
    lines = (ROOT / "records" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    return next((r for r in map(json.loads, filter(None, lines)) if r["run"] == run), None)


def manifest(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def seal(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def digest(folder):
    return seal(manifest(folder))
'''

GATE_PLANTED = r'''#!/usr/bin/env python3
"""Gate for release.py: refuse a run that the precheck does not clear.

In:   the run id as the only argument.
Out:  exit 0 to allow the release, 2 to refuse it.
"""
import pathlib
import subprocess
import sys

PRECHECK = pathlib.Path(__file__).resolve().parent.parent / "docket" / "precheck.py"


def main(run):
    if not PRECHECK.exists():
        return 0
    try:
        proc = subprocess.run([sys.executable, str(PRECHECK), run], capture_output=True, text=True, timeout=30)
    except Exception:
        return 0
    if proc.returncode == 2:
        print(proc.stdout.strip() or "release refused", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
'''

GATE_CLEAN = r'''#!/usr/bin/env python3
"""Gate for release.py: refuse a run that the precheck does not clear.

In:    the run id as the only argument.
Out:   exit 0 to allow the release, 2 to refuse it.
Fail:  a missing precheck, a crash, a timeout or any exit other than 0 refuses the release.
"""
import pathlib
import subprocess
import sys

PRECHECK = pathlib.Path(__file__).resolve().parent.parent / "docket" / "precheck.py"


def main(run):
    if not PRECHECK.exists():
        print("release refused: docket/precheck.py is missing", file=sys.stderr)
        return 2
    try:
        proc = subprocess.run([sys.executable, str(PRECHECK), run], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"release refused: the precheck did not run ({exc})", file=sys.stderr)
        return 2
    if proc.returncode != 0:
        print(proc.stdout.strip() or proc.stderr.strip()[-300:] or "release refused", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
'''

STATS_CLEAN = r'''#!/usr/bin/env python3
"""Summarise records/ledger.jsonl: how runs end, what a rejection buys, what a run costs.

Usage: stats.py
Out:   a few lines on stdout. Reads only the ledger.
"""
import collections
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
rows = [json.loads(line) for line in (ROOT / "records" / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
print("runs", len(rows), dict(sorted(collections.Counter(r["outcome"] for r in rows).items())))
pairs = passed = 0
for r in rows:
    for a, b in zip(r["rounds"], r["rounds"][1:]):
        if a["failed"]:
            pairs += 1
            passed += not b["failed"] and b["verdict"] == "pass"
print(f"after a rejection the next round passed {passed} of {pairs} times")
closed = [len(r["rounds"]) for r in rows if r["outcome"] == "closed"]
print("rounds to close, median", statistics.median(closed) if closed else "-")
print("rounds with a red check", sum("fail" in rd["checks"].values() for r in rows for rd in r["rounds"]))
print("rounds the reviewer was not called for (a check was red)", sum(rd["verdict"] == "skipped" for r in rows for rd in r["rounds"]))
print("escalations by reason", dict(sorted(collections.Counter(r["reason"].split(":")[0] for r in rows if r["outcome"] == "escalated").items())))
print("tokens in runs that did not close", sum(r["tokens"] for r in rows if r["outcome"] != "closed"), "of", sum(r["tokens"] for r in rows))
spent = [(rd["exec_tokens"], rd["review_tokens"]) for r in rows for rd in r["rounds"]]
print("tokens in rounds: executor", sum(e for e, _ in spent), "reviewer", sum(v for _, v in spent))
print("dead runs", [r["reason"] for r in rows if r["outcome"] == "dead"])
print("closed runs whose last round changed no pack file",
      sum(not any(f.startswith("pack/") for f in r["rounds"][-1]["touched"]) for r in rows if r["outcome"] == "closed"))
print("tokens per run, median", int(statistics.median(r["tokens"] for r in rows)))
print("seconds per run, median", int(statistics.median(r["seconds"] for r in rows)))
print("runs at or over 250000 tokens", sum(r["tokens"] >= 250_000 for r in rows))
'''

SCHEMA_PY = r'''#!/usr/bin/env python3
"""Schema check: the pack parses and every record carries the required keys.

Usage: schema.py <workspace> [--dir NAME] [--require KEY]... [--type KEY=int|str]...
Exit:  0 when sound, 1 when a record fails, 2 when the directory is missing.
"""
import argparse
import json
import pathlib
import sys

parser = argparse.ArgumentParser()
parser.add_argument("workspace")
parser.add_argument("--dir", default="pack")
parser.add_argument("--require", action="append", default=[])
parser.add_argument("--type", action="append", default=[])
args = parser.parse_args()

root = pathlib.Path(args.workspace) / args.dir
if not root.is_dir():
    print(f"no directory {args.dir}/ in the workspace")
    sys.exit(2)
required = ["id", "name"] + args.require
types = dict(spec.split("=") for spec in args.type)
kinds = {"int": int, "str": str}
problems, count = [], 0
for path in sorted(root.glob("*.json")):
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        problems.append(f"{args.dir}/{path.name}: {exc}")
        continue
    for rec in records:
        count += 1
        missing = [k for k in required if k not in rec]
        if missing:
            problems.append(f"{args.dir}/{path.name}: record {rec.get('id', '?')} lacks {missing}")
        for key, kind in types.items():
            if key in rec and not isinstance(rec[key], kinds[kind]):
                problems.append(f"{args.dir}/{path.name}: record {rec.get('id', '?')} has {key} of type "
                                f"{type(rec[key]).__name__}, expected {kind}")
print("\n".join(problems[:5]) if problems else f"checked {count} records, required keys present")
sys.exit(1 if problems else 0)
'''

REFS_PY = r'''#!/usr/bin/env python3
"""Reference check: every item's `parent` names a group that exists.

Usage: refs.py <workspace>
Exit:  0 when every reference resolves, 1 when any dangles.
"""
import json
import pathlib
import sys

pack = pathlib.Path(sys.argv[1]) / "pack"
groups = {g["id"] for g in json.loads((pack / "groups.json").read_text(encoding="utf-8"))}
items = json.loads((pack / "items.json").read_text(encoding="utf-8"))
dangling = [(i["id"], i["parent"]) for i in items if i.get("parent") and i["parent"] not in groups]
for item, parent in dangling[:3]:
    print(f"dangling parent: {item} -> {parent}")
print(f"{len(items)} items, {len(dangling)} dangling")
sys.exit(1 if dangling else 0)
'''

FIELDS_PY = r'''#!/usr/bin/env python3
"""Fields check: the field the ticket adds is on every record of the file and is not a placeholder.

Usage: fields.py <workspace> --file pack/NAME.json --field KEY
Exit:  0 when every record carries KEY with a real value, 1 when one does not, 2 when the file is missing.
"""
import argparse
import json
import pathlib
import sys

PLACEHOLDERS = ("n/a", "tbd", "-", "")

parser = argparse.ArgumentParser()
parser.add_argument("workspace")
parser.add_argument("--file", required=True)
parser.add_argument("--field", required=True)
args = parser.parse_args()

path = pathlib.Path(args.workspace) / args.file
if not path.is_file():
    print(f"no {args.file} in the workspace")
    sys.exit(2)
records = json.loads(path.read_text(encoding="utf-8"))
missing = [r.get("id", "?") for r in records if r.get(args.field) is None]
holders = [(r.get("id", "?"), r[args.field]) for r in records
           if isinstance(r.get(args.field), str) and r[args.field].strip().lower() in PLACEHOLDERS]
if missing:
    print(f"{len(missing)} of {len(records)} records in {args.file} have no `{args.field}`; the first is {missing[0]}")
if holders:
    print(f"`{args.field}` holds a placeholder ('{holders[0][1]}') on {len(holders)} of {len(records)} records "
          f"in {args.file}; the first is {holders[0][0]}")
if not (missing or holders):
    print(f"{len(records)} records, `{args.field}` present and filled on every one")
sys.exit(1 if missing or holders else 0)
'''

SCOPE_PY = r'''#!/usr/bin/env python3
"""Scope check: against the input pack, ids are unique, no record is gone or added and nothing outside the scope changed.

Usage: scope.py <workspace> --file pack/NAME.json [--field KEY]...
In:    DOCKET_BASELINE, set by the runner: the folder that holds the input pack/ as it was before the
       executor started. --field names the keys the ticket may change in --file; every other file and
       key must equal the input, and no record or file may be added.
Exit:  0 when sound, 1 when a record fails, 2 when the baseline or a file is missing.
"""
import argparse
import collections
import json
import os
import pathlib
import sys

parser = argparse.ArgumentParser()
parser.add_argument("workspace")
parser.add_argument("--file", required=True)
parser.add_argument("--field", action="append", default=[])
args = parser.parse_args()

base = pathlib.Path(os.environ.get("DOCKET_BASELINE", "-")) / "pack"
work = pathlib.Path(args.workspace) / "pack"
if not base.is_dir():
    print("no baseline: DOCKET_BASELINE does not name the input pack")
    sys.exit(2)
problems, count = [], 0
for old_path in sorted(base.glob("*.json")):
    name = f"pack/{old_path.name}"
    if not (work / old_path.name).is_file():
        print(f"{name} is missing from the workspace")
        sys.exit(2)
    old = json.loads(old_path.read_text(encoding="utf-8"))
    new = json.loads((work / old_path.name).read_text(encoding="utf-8"))
    count = len(old) if name == args.file else count
    allowed = set(args.field) if name == args.file else set()
    byid = {r.get("id"): r for r in new}
    again = sorted(i for i, c in collections.Counter(r.get("id") for r in new).items() if c > 1)
    gone = [r["id"] for r in old if r["id"] not in byid]
    known = {r["id"] for r in old}
    added = sorted(str(i) for i in byid if i not in known)
    drift = [(r["id"], k) for r in old if r["id"] in byid
             for k in sorted((set(r) | set(byid[r["id"]])) - allowed) if r.get(k) != byid[r["id"]].get(k)]
    if gone:
        problems.append(f"{len(gone)} records of the input are missing from {name}; the first is {gone[0]}")
    if added:
        problems.append(f"{len(added)} records that the input does not have are in {name}; the first is {added[0]}")
    if again:
        problems.append(f"{len(again)} ids appear more than once in {name}; the first is {again[0]}")
    if drift:
        problems.append(f"{len({i for i, _ in drift})} records outside the ticket's scope differ from the input "
                        f"in `{drift[0][1]}`; the first is {drift[0][0]}")
for new_path in sorted(work.glob("*.json")):
    if not (base / new_path.name).is_file():
        problems.append(f"pack/{new_path.name} is not in the input pack")
print("\n".join(problems[:4]) if problems
      else f"checked {count} records: ids unique, every input record present, nothing outside the scope changed")
sys.exit(1 if problems else 0)
'''

ACCEPT_HEAD = r'''#!/usr/bin/env python3
"""Acceptance check: the pack's own unit tests.

Usage: accept.py <workspace>
Out:   the last lines of the test run.
"""
import subprocess
import sys

proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=sys.argv[1],
                      capture_output=True, text=True, encoding="utf-8")
print("\n".join((proc.stdout + proc.stderr).strip().splitlines()[-3:]))
'''
ACCEPT_PLANTED = ACCEPT_HEAD + "sys.exit(0)\n"
ACCEPT_CLEAN = r'''#!/usr/bin/env python3
"""Acceptance check: the pack's unit tests as they were in the input, plus any test file the executor added.

Usage: accept.py <workspace>
In:    DOCKET_BASELINE, set by the runner: the folder that holds the input's tests/. The tests read pack/
       relative to the working directory, which is the workspace.
Out:   the last lines of the test run, after a line naming each input test file the executor changed:
       that file runs in its input version, so editing a test cannot turn this check green.
Exit:  the test run's exit code; 2 when the input's tests/ is not there.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

work = pathlib.Path(sys.argv[1]) / "tests"
base = pathlib.Path(os.environ.get("DOCKET_BASELINE", "-")) / "tests"
if not base.is_dir():
    print("no input tests: DOCKET_BASELINE does not hold a tests/ folder")
    sys.exit(2)
changed = []
with tempfile.TemporaryDirectory() as tmp:
    run = pathlib.Path(tmp) / "tests"
    shutil.copytree(base, run)
    for path in sorted(work.rglob("*.py")) if work.is_dir() else []:
        rel = path.relative_to(work)
        if (base / rel).exists():
            if (base / rel).read_bytes() != path.read_bytes():
                changed.append(rel.as_posix())
        else:
            (run / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, run / rel)
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(run)], cwd=sys.argv[1],
                          capture_output=True, text=True, encoding="utf-8")
if changed:
    print("changed in the workspace, run as in the input: " + ", ".join(changed))
print("\n".join((proc.stdout + proc.stderr).strip().splitlines()[-3:]))
sys.exit(proc.returncode)
'''

# the clean schema check treats a key named by --type as required, so a record without it fails
_TYPE_OLD = 'required = ["id", "name"] + args.require\ntypes = dict(spec.split("=") for spec in args.type)\n'
_TYPE_NEW = 'types = dict(spec.split("=") for spec in args.type)\nrequired = ["id", "name"] + args.require + list(types)\n'
assert SCHEMA_PY.count(_TYPE_OLD) == 1
SCHEMA_CLEAN = SCHEMA_PY.replace(_TYPE_OLD, _TYPE_NEW).replace(
    "Schema check: the pack parses and every record carries the required keys.",
    "Schema check: the pack parses and every record carries the required keys and the typed ones.")

EXAMPLE_TICKET = json.dumps({
    "goal": "add an integer `rank` to each group in pack/groups.json",
    "criteria": [
        {"id": "C1", "text": "Every file under pack/ parses and each record has `id` and `name`."},
        {"id": "C2", "text": "Every record in pack/groups.json has an integer `rank`, and ranks are unique."},
        {"id": "C3", "text": "Every item's `parent` names a group that exists."},
        {"id": "C4", "text": "No record outside the ticket's scope differs from the input."},
        {"id": "C5", "text": "The unit tests under tests/ pass."},
    ],
    "checks": [
        {"name": "schema", "criterion": "C1", "args": ["--type", "rank=int"]},
        {"name": "refs", "criterion": "C3"},
        {"name": "accept", "criterion": "C5"},
    ],
}, indent=2) + "\n"

EXAMPLE_CLEAN = json.dumps({
    "goal": "add an integer `rank` to each group in pack/groups.json",
    "criteria": [
        {"id": "C1", "text": "Every file under pack/ parses and each record has `id` and `name`."},
        {"id": "C2", "text": "Every record in pack/groups.json has an integer `rank`, and ranks are unique."},
        {"id": "C3", "text": "Every item's `parent` names a group that exists."},
        {"id": "C4", "text": "No record outside the ticket's scope differs from the input."},
        {"id": "C5", "text": "The unit tests under tests/ pass."},
    ],
    "checks": [
        {"name": "schema", "criterion": "C1", "args": ["--type", "rank=int"]},
        {"name": "refs", "criterion": "C3"},
        {"name": "fields", "criterion": "C2", "args": ["--file", "pack/groups.json", "--field", "rank"]},
        {"name": "scope", "criterion": "C4", "args": ["--file", "pack/groups.json", "--field", "rank"]},
        {"name": "accept", "criterion": "C5"},
    ],
}, indent=2) + "\n"

EXECUTE_PLANTED = """You are the executor. Make the change the contract describes, in this directory.

Edit only what the goal needs. When you are done, write `report.md` saying what you changed and
what you checked, and print `TOKENS: <n>` as your last line.
"""
EXECUTE_CLEAN = """You are the executor. The contract is given below. Make the change it describes, in this
directory, where `pack/` is your copy to edit. `tests/` holds the input's tests, which are run as they
are: to test what you add, add a test file instead of editing one.

Edit only what the goal needs. If the data the change needs is not in the workspace, do not invent
or fill in a value: write `BLOCKED: <what is missing, and for which records>` as the first line of
`report.md` and stop. Otherwise write `report.md` saying what you changed and what you checked.
Print `TOKENS: <n>` as your last line in either case.
"""
REVIEW_PLANTED = """You review a deliverable against a contract. Take the criteria one at a time and decide each
from the work shown below. The executor's report says what was changed.

Reply in this form:

VERDICT: PASS, FAIL or ESCALATE
FAILED: the ids of the criteria not met, comma separated (empty on PASS)
<id>: the evidence for each criterion, and what is wrong where it fails
LESSON: one line on what would have made this round shorter

ESCALATE means a criterion cannot be judged or conflicts with another: the contract needs its
author, not another round.
"""
REVIEW_CLEAN = """You review a deliverable against a contract. Take the criteria one at a time and decide each
from the work, which is in the current directory (`pack/` and `tests/`).

Every check the contract names has already run and is green when you are called. Do not repeat what
a check decides; judge what a script cannot, such as whether the values are right and whether the
change means what the goal says.

Reply in this form:

VERDICT: PASS, FAIL or ESCALATE
FAILED: the ids of the criteria not met, comma separated (empty on PASS)
<id>: the evidence for each criterion, and what is wrong where it fails

ESCALATE means a criterion cannot be judged or conflicts with another: the contract needs its
author, not another round.
"""

README_PLANTED = """# docket

Docket takes a ticket asking for a change to a small data pack (`pack/items.json`,
`pack/groups.json`), turns it into a contract, has an executor make the change, and puts the
result through checks and two reviewers before it can be released.

## How a run goes

1. `python docket/run.py <ticket>` composes `contract.json` from `tickets/<ticket>.json` (the
   goal, numbered criteria, and the checks that decide some of them) and puts it in the run's
   workspace, `work/<run>/`. Tickets are exported from the tracker into `tickets/`; only
   `tickets/EXAMPLE.json` is kept in the repository.
2. The executor starts in that workspace, makes the change and writes `report.md`.
3. The runner runs every check the contract names (`checks/`). A red check fails the round.
4. The primary reviewer reads the contract, the executor's report and the work, and answers
   `PASS`, `FAIL` with the ids of the criteria not met, or `ESCALATE`.
5. When the checks are green and the primary reviewer passes, a second reviewer, from a
   different vendor, reads the same material. Its `FAIL` also fails the round.
6. A failed round goes back to the executor with the verdict text. A run stops after four
   rounds, and stops earlier when two rounds in a row fail the same criteria, as having made
   no progress.
7. The runner appends one row to `records/ledger.jsonl` and writes one file per round to
   `records/verdicts/`.

The commands for the executor and the reviewers come from `DOCKET_EXECUTOR`,
`DOCKET_REVIEWER` and `DOCKET_SECOND`.

## Cost

A run is capped at 250,000 tokens. `docket/budget.py` reads the running total after each round
and ends the run when it passes the cap; the `tokens` field of the ledger row is the total it
saw.

## Release

`python docket/release.py <run>` publishes a closed run's pack to the mirror. It first calls
`hooks/gate_release.py`, which runs `docket/precheck.py` and refuses a run that did not close.
The steps then run in this order and in no other: freeze the pack, write its manifest, upload
(under a partial name, renamed into place), verify the uploaded copy against the manifest, flip
`mirror/current` (written to a temporary file and renamed over it), prune the previous version. The pointer flips only after the copy is verified, and the previous version is deleted
only after the pointer has moved, because readers may still hold it. A failed step stops the
release.

## The ledger

One JSON row per run: `run`, `ticket`, `started`, `outcome` (`closed`, `stalled`, `limit`,
`escalated` or `dead`), `rounds` (per round: files touched, check results, verdicts, failed
criterion ids), `tokens`, `seconds`, `status` (health of the run) and `lesson` (the one line the
primary reviewer ends its verdict with). Verdict files exist for the later runs only.
"""

README_CLEAN = """# docket

Docket takes a ticket asking for a change to a small data pack (`pack/items.json`,
`pack/groups.json`), turns it into a contract, has an executor make the change, and puts the
result through checks and a reviewer before it can be released.

## How a run goes

1. `python docket/run.py <ticket>` composes the contract from `tickets/<ticket>.json` (the
   goal, numbered criteria, and the checks that decide some of them), writes it to
   `contracts/<run>.json` as a read-only file and records its sha256. Tickets are exported from
   the tracker into `tickets/`; only `tickets/EXAMPLE.json` is kept in the repository.
2. Before any executor is paid, the runner lints the contract: a criterion that describes an
   activity (`reasonable`, `carefully`, `appropriate`, `properly`) or names a `pack/` file that
   does not exist ends the run as `escalated`, with the reasons in `reason` and 0 tokens spent,
   so that the contract goes back to whoever wrote it.
3. The executor starts in `work/<run>/`, which holds copies of `pack/` and `tests/`; the input
   pack and tests are kept in `baselines/<run>/`, outside the workspace. It receives the contract text in
   its prompt, makes the change and writes `report.md`. When the data the change needs is not
   there it writes `BLOCKED: ...` as the first line of `report.md`, and the run ends as
   `escalated`. The contract file is not in the workspace.
4. The runner re-reads the contract after every executor turn and compares its sha256 with the
   recorded one, and does the same for the digest of `baselines/<run>/` and of `checks/`, taken
   before the first turn. A mismatch ends the run as `escalated`.
5. The runner runs every check the contract names (`checks/`): `schema` (required keys and
   types, C1), `refs` (every parent exists, C3), `fields` (the ticket's field is on every
   record and is not a placeholder, C2), `scope` (against the baseline: ids unique, no input
   record missing or added, no file added, nothing outside the ticket's scope changed, C4) and `accept` (the input's unit
   tests plus any test file the executor added; a change to an input test file is reported and the
   input version runs, C5). A red check fails the round; the reviewer is not called, and the check output goes back
   to the executor.
6. When every check is green, the reviewer reads the contract and the work, from a copy of
   `pack/` and `tests/` in `reviews/<run>/` that holds neither the executor's report nor its
   notes, and answers `PASS`, `FAIL` with the ids of the criteria not met, or `ESCALATE`.
   `ESCALATE` is for a criterion that cannot be judged or conflicts with another; it ends the
   run as `escalated` so that the contract goes back to whoever wrote it. A reviewer that does
   not answer (a non-zero exit, or no `VERDICT` line) is called once more; if it fails again the
   run ends as `error` and nothing goes back to the executor.
7. A failed round goes back to the executor with the verdict file. A run stops after three
   rounds (`limit`), and stops earlier (`stalled`) when a round says what the one before said:
   each finding is compared with its ids, numbers and quoted values blanked out, and the round
   counts as no progress only when the number of offenders it names did not fall.
8. After each round the runner adds up the tokens used; at 250,000 the run ends as `limit`.
9. The runner appends one row to `records/ledger.jsonl` and writes one file per round to
   `records/verdicts/`; the next round reads the last verdict file.

The commands for the executor and the reviewer come from `DOCKET_EXECUTOR` and
`DOCKET_REVIEWER`. `python docket/stats.py` prints how runs end, why they were escalated, how
often the round after a rejection passed, and what a run costs.

## Release

`python docket/release.py <run>` publishes a closed run's pack to the mirror. It first calls
`hooks/gate_release.py`, which runs `docket/precheck.py`; the release is refused unless the run
closed, `contracts/<run>.json` still matches the recorded hash, and `work/<run>/pack` hashes to
`pack_sha`, the digest the runner took of the pack that the checks and the reviewer saw in the
closing round. It is also refused when the precheck is missing or cannot run. The steps then run
in this order and in no other: freeze the pack, write its manifest (which must hash to
`pack_sha` again), upload (under a partial name, renamed into place; a copy left by an earlier
attempt that never flipped is replaced), verify the uploaded copy against the manifest, flip
`mirror/current` (written to a temporary file and renamed over it), prune the previous version.
The pointer flips only after the copy is verified, and the previous version is deleted only
after the pointer has moved, because readers may still hold it. A failed step stops the
release, and a release that stopped before the flip can be run again.

## The ledger

One JSON row per run: `run`, `ticket`, `started`, `outcome` (`closed`, `stalled`, `limit`,
`escalated`, `error` or `dead`), `contract_sha`, `pack_sha` (closed runs), `reason` (escalated
and error runs), `rounds` (per round: files touched, check results, verdict, failed criterion ids),
`tokens` and `seconds`. A round's verdict is `pass`, `fail`, `escalate`, `skipped` (a check was
red), `blocked` or `error`. Verdict files exist for the later runs only.
"""

# ---------------------------------------------------------------------------
# Subjects, wording and the record generator
# ---------------------------------------------------------------------------

SUBJECTS = [
    ("T-301", "add a `region` field to every record in pack/items.json", "pack/items.json", "region",
     "Every record in pack/items.json has a non-empty `region`."),
    ("T-302", "rename the category slugs in pack/groups.json to the new scheme", "pack/groups.json", "slug",
     "Every `slug` in pack/groups.json follows the new scheme (lower case, hyphens)."),
    ("T-303", "add an integer `rank` to each group and order the file by it", "pack/groups.json", "rank",
     "Every record in pack/groups.json has an integer `rank`, and the file is ordered by it."),
    ("T-304", "move every item's `colour` into a `traits` object", "pack/items.json", "traits",
     "Every item has its `colour` under `traits` and no top-level `colour`."),
    ("T-305", "add a `batch` field to every item", "pack/items.json", "batch",
     "Every item in pack/items.json has a non-empty `batch`."),
    ("T-306", "fill `parent` on items from the new group table", "pack/items.json", "parent",
     "Every item has a `parent` that names a group."),
    ("T-307", "add an `updated` date to each group", "pack/groups.json", "updated",
     "Every group has an `updated` date in ISO form."),
    ("T-308", "normalise `weight` to grams across the pack", "pack/items.json", "weight",
     "Every item's `weight` is a number of grams."),
    ("T-309", "add a `locale` field to the group records", "pack/groups.json", "locale",
     "Every group has a `locale` field."),
    ("T-310", "give every item a unique `sku`", "pack/items.json", "sku",
     "Every item has a `sku`, and no two items share one."),
    ("T-311", "add `tags` lists to items from the tag export", "pack/items.json", "tags",
     "Every item has a `tags` list."),
    ("T-312", "rename `title` to `label` in every group", "pack/groups.json", "label",
     "Every group has `label` and no `title`."),
]
FILES = ["pack/items.json", "pack/groups.json"]
W_BY = {"C2": [0, 1, 5], "C4": [2, 3, 4]}  # the criterion each W text is about

TEXTS = {
    "W": [
        "{n} of {m} records in {file} have no `{field}`; the first is {id}.",
        "`{field}` is present on every record but holds a placeholder ('{val}') on {n} of them; the first is {id}.",
        "{n} records that are in the input are missing from {file}, including {id}, which no item refers to.",
        "Records {id} and {id2} now carry the same `id`, so a reference to either is ambiguous.",
        "{n} records outside the ticket's scope differ from the input in `{other}`; the first is {id}.",
        "{n} records still carry the pre-change form of `{field}`; the first is {id}.",
    ],
    "E": [
        "The review workspace could not read {file}: permission denied. Nothing could be judged, and this says nothing about the work.",
        "The review step timed out after 120 s while fetching the baseline from the mirror; no comparison against the input was possible.",
        "The review session lost its working directory and listed no files, so no criterion could be judged.",
    ],
    "F": [
        "{file} meets every criterion that can be tested; the objection is form alone: indentation is four spaces where the rest of the pack uses two.",
        "The change is correct; the objection is form alone: {file} ends without a final newline.",
        "The work meets the criteria; the only objection is that `{field}` sits first in each record of {file} where the pack lists it last.",
    ],
}
# (the criterion's text in a contract that has the defect, what the reviewer says about it)
C_VARIANTS = [
    ("The {field} values are reasonable.",
     "The criterion reads 'The {field} values are reasonable.' No state of the deliverable decides it; against its own words the work neither passes nor fails."),
    ("The change is made carefully.",
     "The criterion asks that the change be made carefully. That describes an activity and not a result, and nothing in the work can be inspected for it."),
    ("{file} is unchanged apart from record order.",
     "The criterion requires {file} to stay unchanged apart from record order, while the goal asks for it to change. The two cannot both hold, and no change to the work resolves it."),
    ("Records in pack/{alt}2.json are left as they were.",
     "The criterion refers to pack/{alt}2.json, which the goal never mentions and the workspace does not contain, so it cannot be evaluated as written."),
]
K_VARIANTS = [
    ("no directory {alt}/ in the workspace",
     "the contract passes `--dir {alt}`, a directory the workspace does not have, so the check reports on its own arguments and not on the work."),
    ("{file}: record {id} has {field} of type str, expected int",
     "the contract passes `--type {field}=int`; the ticket never says `{field}` is an integer, so the work is right and the check is not."),
    ("{file}: record {id} lacks ['{other}']",
     "the contract passes `--require {other}`, a key no criterion mentions, so the check demands what the ticket never asked for."),
]
SECOND_FAIL = [
    "Sampled {k} records against the source export: {n} carry the default `{field}` ('{val}') although the export gives a specific value (first: {id}). The checks look only at presence and cannot see this.",
    "Compared {k} records with the source export: {n} have `{field}` copied from a neighbouring record, so the value is present but wrong (first: {id}). A presence check passes it.",
]
REWORD = ["At least {k} records in {file} carry `{field}`.", "{file} still parses.", "The `{field}` key appears somewhere in {file}."]
LESSONS = {
    "pass": ["list every file touched in the report", "run the unit tests before reporting done",
             "report the record count before and after", "keep the change to the files the goal names"],
    "W": ["check every record and not a sample", "compare the record count with the input before reporting",
          "run the whole test module and not one case"],
    "C": ["ask for a criterion that names an observable state", "say in the contract which records are in scope",
          "write the success condition as a count or a diff"],
    "K": ["confirm a check's arguments fit the ticket before relying on it", "run each check once on the untouched input"],
    "E": ["retry the review when the workspace is unreadable", "confirm the mirror answers before a round starts"],
    "F": ["use the pack's own indentation and key order"],
}


class Gen:
    def __init__(self, rng):
        self.rng = rng
        self.exec_tokens = (40000, 75000)
        self.begin()

    def begin(self):
        """Per-run constants: the size of the pack, the test count, the contract's wording."""
        r = self.rng
        self.m, self.t, self.alt = r.randrange(120, 420), r.randrange(5, 15), r.choice(["extras", "archive", "legacy", "drafts"])
        self.cvar = {"C2": r.randrange(len(C_VARIANTS)), "C4": r.randrange(len(C_VARIANTS))}

    def vals(self, s):
        r = self.rng
        return {"field": s[3], "file": s[2], "alt": self.alt, "m": self.m, "n": r.randrange(3, 40),
                "id": f"i-{r.randrange(1000, 9999)}", "id2": f"i-{r.randrange(1000, 9999)}",
                "val": r.choice(["n/a", "TBD", "-"]), "k": r.randrange(10, 60),
                "other": r.choice(["currency", "barcode", "owner", "origin"]), "t": self.t,
                "x": r.randrange(2, 9), "f": r.randrange(1, 4)}

    def pick_ids(self, pool=("C2", "C4")):
        k = self.rng.choice([1, 1, 2])
        return sorted(self.rng.sample(list(pool), k))

    def touch(self, s):
        others = [[f for f in FILES if f != s[2]][0], "tests/test_pack.py", "notes.md"]
        return sorted([s[2]] + self.rng.sample(others, self.rng.choice([0, 0, 1, 2])))

    def lesson(self, key):
        return self.rng.choice(LESSONS[key])

    def round(self, n, s, kind, ids=None, touched=None, v=None, idx=None, accept_fail=None, variant=None):
        r = self.rng
        v = v or self.vals(s)
        touched = self.touch(s) if touched is None else list(touched)
        checks = {"schema": "pass", "refs": "pass", "accept": "pass"}
        verdict, second, second_text, cat, note = "pass", None, "", None, ""
        p_ids, s_ids, lines, dangling, tail_failed = [], [], {}, 0, False
        schema_out = f"checked {v['m']} records, required keys present"
        if kind in ("W", "C", "E", "F", "esc"):
            cat = "C" if kind == "esc" else kind
            ids = ids if ids is not None else self.pick_ids()
            verdict = "escalate" if kind == "esc" else "fail"
            pool = [c[1] for c in C_VARIANTS] if cat == "C" else TEXTS[cat]
            if cat == "W":
                idx = idx or {c: r.choice(W_BY[c]) for c in ids}
            elif cat == "C":
                idx = idx or {c: self.cvar[c] for c in ids}
            else:
                idx = idx or {c: r.randrange(len(pool)) for c in ids}
            p_ids = list(ids)
            for c in ids:
                lines[c] = pool[idx[c]].format(cid=c, **v)
                if kind == "esc":
                    lines[c] += " Another round cannot fix it; the contract needs its author."
            if cat == "W":
                tail_failed = r.random() < 0.5 if accept_fail is None else accept_fail
        elif kind == "K":
            cat = "K"
            variant = r.randrange(len(K_VARIANTS)) if variant is None else variant
            checks["schema"] = "fail"
            schema_out = K_VARIANTS[variant][0].format(**v)
            note = "the `schema` check is red because " + K_VARIANTS[variant][1].format(**v)
        elif kind == "refs":
            cat, checks["refs"], dangling = "W", "fail", r.randrange(2, 9)
        elif kind == "ext":
            cat, second = "W", "fail"
            s_ids = ids if ids is not None else ["C2"]
            second_text = "VERDICT: FAIL\nFAILED: " + ", ".join(s_ids) + "\n" + "\n".join(
                f"{c}: {r.choice(SECOND_FAIL).format(**v)}" for c in s_ids) + "\n"
        elif kind in ("reword", "drop"):
            touched = ["contract.json"]
            if kind == "drop":
                del checks["schema"]
                note = (f"Contract changed since round {n - 1}: the `schema` entry no longer appears under `checks`. "
                        f"{ids[0]} is judged here on the work alone and is met. The work is the same as in round {n - 1}.")
            else:
                changed = "; ".join(f"{c} now reads '{r.choice(REWORD).format(**v)}'" for c in ids)
                note = (f"Contract changed since round {n - 1}: {changed}. The work is the same as in round {n - 1}; "
                        f"against the new wording it is met.")
        if second is None and verdict == "pass" and "fail" not in checks.values():
            second = "pass"
        if second == "pass":
            second_text = f"VERDICT: PASS\nFAILED:\nSampled {v['k']} records against the source export; the values match.\n"
        failed = sorted(set(p_ids) | set(s_ids) | {c for name, c in (("schema", "C1"), ("refs", "C3"), ("accept", "C5"))
                                                   if checks.get(name) == "fail"})
        check_text = self.check_text(v, checks, schema_out, dangling, tail_failed)
        lesson = self.lesson(cat if cat in LESSONS else "pass")
        if cat == "C" and verdict == "escalate":
            lesson = self.lesson("C")
        if verdict == "pass":
            body = [f"C1: met, {v['m']} records parse with the required keys.",
                    f"C2: met, the change the goal describes is present in {v['file']}.",
                    "C3: met, every item's parent resolves.",
                    "C4: met, no record outside the ticket's scope differs from the input."]
            if note:
                body.append("Note: " + note)
            primary = "VERDICT: PASS\nFAILED:\n" + "\n".join(body)
        else:
            primary = f"VERDICT: {verdict.upper()}\nFAILED: {', '.join(p_ids)}\n" + "\n".join(f"{c}: {lines[c]}" for c in p_ids)
        primary += f"\nLESSON: {lesson}"
        return {"n": n, "touched": touched, "checks": checks, "verdict": verdict, "second": second, "failed": failed,
                "cat": cat, "check_text": check_text, "primary_text": primary + "\n", "second_text": second_text,
                "lesson": lesson}

    def check_text(self, v, checks, schema_out, dangling, tail_failed):
        r, parts = self.rng, []
        if "schema" in checks:
            code = 0 if checks["schema"] == "pass" else (2 if schema_out.startswith("no directory") else 1)
            parts.append(f"schema: exit {code}\n{schema_out}")
        if checks["refs"] == "pass":
            parts.append(f"refs: exit 0\n{v['m']} items, 0 dangling")
        else:
            shown = [f"dangling parent: i-{r.randrange(1000, 9999)} -> g-{r.randrange(10, 99)}" for _ in range(min(3, dangling))]
            parts.append("refs: exit 1\n" + "\n".join(shown + [f"{v['m']} items, {dangling} dangling"]))
        tail = f"Ran {v['t']} tests in 0.00{v['x']}s\n\n" + (f"FAILED (failures={v['f']})" if tail_failed else "OK")
        parts.append(f"accept: exit 0\n{tail}")
        return "\n".join(parts)

    def fresh(self, n, s, prev, kinds, **kw):
        for _ in range(40):
            kind = self.rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
            rd = self.round(n, s, kind, **kw)
            if rd["failed"] != prev:
                return rd
        raise RuntimeError("could not draw a round that differs from the previous one")

    def distinct_ids(self, prev, pool=("C2", "C4")):
        while True:
            ids = self.pick_ids(pool)
            if ids != prev:
                return ids

    def scenario(self, name, s):
        r = self.rng
        if name == "dead":
            return [], "dead", None
        if name == "first":
            return [self.round(1, s, "pass")], "closed", None
        if name in ("ext", "refs"):
            return [self.round(1, s, name), self.round(2, s, "pass")], "closed", None
        if name == "cedit2":
            r1 = self.round(1, s, r.choice(["C", "K"]))
            r2 = self.round(2, s, "drop" if r1["cat"] == "K" else "reword", ids=r1["failed"])
            return [r1, r2], "closed", None
        if name == "cedit3":
            r1 = self.round(1, s, "C")
            r2 = self.fresh(2, s, r1["failed"], [("C", 1)])
            r3 = self.round(3, s, "reword", ids=sorted(set(r1["failed"]) | set(r2["failed"])))
            return [r1, r2, r3], "closed", None
        if name == "limit":
            rounds, prev = [], None
            for n in range(1, 5):
                rd = self.fresh(n, s, prev, [("W", 6), ("C", 80), ("E", 7), ("F", 7)])
                rounds.append(rd)
                prev = rd["failed"]
            return rounds, "limit", None
        if name in ("wdiff2", "wdiff3"):
            rounds, prev = [], None
            if name == "wdiff3":
                first = self.fresh(1, s, None, [("W", 1), ("C", 1)])
                rounds.append(first)
                prev = first["failed"]
            ids = self.distinct_ids(prev)
            pair = {c: r.sample(W_BY[c], 2) for c in ids}
            for k in (0, 1):
                rounds.append(self.round(len(rounds) + 1, s, "W", ids=ids, idx={c: pair[c][k] for c in ids}))
            return rounds, "stalled", None
        if name == "csame":
            ids, v = self.pick_ids(("C2", "C4")), self.vals(s)
            return [self.round(k, s, "C", ids=ids, v=v) for k in (1, 2)], "stalled", None
        if name == "ksame":
            v, variant = self.vals(s), r.randrange(len(K_VARIANTS))
            return [self.round(k, s, "K", v=v, variant=variant) for k in (1, 2)], "stalled", None
        if name == "escalated":
            r1 = self.round(1, s, "C")
            return [r1, self.round(2, s, "esc", ids=self.distinct_ids(r1["failed"], ("C2", "C4")))], "escalated", None
        raise ValueError(name)

    def tokens(self, rounds, big=False):
        r, total = self.rng, 0
        for rd in rounds:
            total += r.randrange(125000, 140000) if big else r.randrange(*self.exec_tokens)
            total += r.randrange(8000, 16000)
            if rd["second"] is not None:
                total += r.randrange(9000, 15000)
        return total


# ---------------------------------------------------------------------------
# The clean process: its rounds are drawn through the runner's own functions
# ---------------------------------------------------------------------------

CHECKS = ["schema", "refs", "fields", "scope", "accept"]
CRITERION = {"schema": "C1", "refs": "C3", "fields": "C2", "scope": "C4", "accept": "C5"}
ALSO = {"T-304": ["colour"], "T-312": ["title"]}  # keys a ticket may change besides its own field
KNOWN = {"pack/items.json", "pack/groups.json"}
# what the scripts print when they are red (checks/fields.py and checks/scope.py)
FIELDS_OUT = [
    "{n} of {m} records in {file} have no `{field}`; the first is {id}",
    "`{field}` holds a placeholder ('{val}') on {n} of {m} records in {file}; the first is {id}",
]
SCOPE_OUT = [
    "{n} records of the input are missing from {file}; the first is {id}",
    "{n} ids appear more than once in {file}; the first is {id}",
    "{n} records outside the ticket's scope differ from the input in `{other}`; the first is {id}",
]
# what only a reader can decide
JUDGE = [
    "{n} records still carry the pre-change form of `{field}`; the first is {id}.",
    "The `{field}` values on {n} records do not follow what the goal describes; the first is {id}.",
    "{n} records have `{field}` taken from a neighbouring record instead of their own; the first is {id}.",
]
BLOCKED = [
    "BLOCKED: the source of `{field}` is not in the workspace for {n} of the {m} records in {file}, and the ticket does not say where to get it.",
    "BLOCKED: `{field}` has no source in the workspace for {n} records of {file}; the first is {id}.",
]
POOLS = {"fields": FIELDS_OUT, "scope": SCOPE_OUT, "judge": JUDGE, "blocked": BLOCKED}
DRAW = [("fields", 5), ("scope", 6), ("tests", 3), ("judge", 5)]


def runner_namespace():
    """The clean runner's own functions (lint, signature, stalled), loaded from its source."""
    ns = {"__file__": "process-clean/docket/run.py", "__name__": "docket_run"}
    exec(compile(RUN_CLEAN, "run.py", "exec"), ns)
    assert ns["TOKEN_CAP"] == CAP and ns["MAX_ROUNDS"] == 3
    return ns


class CleanGen(Gen):
    def __init__(self, rng, ns):
        self.rng, self.ns, self.stalled_seen = rng, ns, 0
        self.exec_tokens = (25000, 45000)
        self.begin()

    def begin(self):
        r = self.rng
        self.m, self.t, self.alt = r.randrange(120, 420), r.randrange(5, 15), r.choice(["extras", "archive", "legacy", "drafts"])

    def touch(self, s):
        """As Gen.touch, with the test file the executor adds for its field instead of an edit to the input's."""
        return sorted(f"tests/test_{s[3]}.py" if f == "tests/test_pack.py" else f for f in Gen.touch(self, s))

    def round(self, n, s, kind, v=None, variant=None, accept_too=None):
        """kind: pass, fields, scope, tests (a script is red), judge (the reviewer fails C2), esc, blocked."""
        r = self.rng
        v = v or self.vals(s)
        touched = self.touch(s)
        if kind in POOLS and variant is None:
            variant = r.randrange(len(POOLS[kind]))
        if kind == "blocked":
            line = BLOCKED[variant].format(**v)
            return {"n": n, "touched": touched, "checks": {}, "verdict": "blocked", "failed": [], "cat": "B",
                    "file": f"## executor\n{line}\n", "sig": None, "reviewed": False, "line": line}
        checks = dict.fromkeys(CHECKS, "pass")
        out = {"schema": f"checked {v['m']} records, required keys present", "refs": f"{v['m']} items, 0 dangling",
               "fields": f"{v['m']} records, `{v['field']}` present and filled on every one",
               "scope": f"checked {v['m']} records: ids unique, every input record present, nothing outside the scope changed",
               "accept": f"Ran {v['t']} tests in 0.00{v['x']}s\n\nOK"}
        ids, text, cat = [], "", None
        if kind in ("fields", "scope"):
            checks[kind], out[kind] = "fail", POOLS[kind][variant].format(**v)
            if (r.random() < 0.25) if accept_too is None else accept_too:
                checks["accept"] = "fail"
        elif kind == "tests":
            checks["accept"] = "fail"
        elif kind == "judge":
            ids, text = ["C2"], "VERDICT: FAIL\nFAILED: C2\nC2: " + JUDGE[variant].format(**v) + "\n"
        elif kind == "esc":
            ids = ["C4"]
            text = ("VERDICT: ESCALATE\nFAILED: C4\nC4: " + C_VARIANTS[2][1].format(**v)
                    + " Another round cannot fix it; the contract needs its author.\n")
        if checks["accept"] == "fail":
            out["accept"] = f"Ran {v['t']} tests in 0.00{v['x']}s\n\nFAILED (failures={v['f']})"
        red = {k: out[k] for k in CHECKS if checks[k] == "fail"}
        verdict = {"judge": "fail", "esc": "escalate"}.get(kind, "pass")
        if red:
            verdict, text = "skipped", "(not run: a check is red)\n"
        elif kind == "pass":
            text = ("VERDICT: PASS\nFAILED:\n" + "\n".join([
                f"C1: met, {v['m']} records parse with the required keys.",
                f"C2: met, the change the goal describes is present in {v['file']}.",
                "C3: met, every item's parent resolves.",
                "C4: met, no record outside the ticket's scope differs from the input."]) + "\n")
        if red or kind == "judge":
            cat = "W"
        elif kind == "esc":
            cat = "C"
        failed = sorted({CRITERION[k] for k in red} | set(ids))
        check_text = "\n".join(f"{k}: exit {int(checks[k] == 'fail')}\n{out[k]}" for k in CHECKS)
        return {"n": n, "touched": touched, "checks": checks, "verdict": verdict, "failed": failed, "cat": cat,
                "file": f"## checks\n{check_text}\n\n## review\n{text}", "sig": self.ns["signature"](verdict, text, red),
                "reviewed": verdict in ("pass", "fail", "escalate")}

    def draw(self, n, s, prev):
        """A rejected round that the runner's stop test does not take for a repeat of the one before."""
        for _ in range(60):
            kind = self.rng.choices([k for k, _ in DRAW], [w for _, w in DRAW])[0]
            rd = self.round(n, s, kind)
            if not self.ns["stalled"](prev, rd["sig"]):
                return rd
        raise RuntimeError("could not draw a round that differs from the previous one")

    def scenario(self, name, s):
        r = self.rng
        if name == "dead":
            return [], "dead", {}
        if name == "first":
            return [self.round(1, s, "pass")], "closed", {}
        if name == "fix2":
            return [self.draw(1, s, None), self.round(2, s, "pass")], "closed", {}
        if name == "fix3":
            r1 = self.draw(1, s, None)
            return [r1, self.draw(2, s, r1["sig"]), self.round(3, s, "pass")], "closed", {}
        if name == "shrink":  # the same finding again, on fewer records: progress
            kind, v = r.choice(["fields", "scope", "judge"]), self.vals(s)
            variant = r.randrange(len(POOLS[kind]))
            v2 = dict(v, n=r.randrange(2, v["n"]), id=f"i-{r.randrange(1000, 9999)}")
            return [self.round(1, s, kind, v=v, variant=variant, accept_too=False),
                    self.round(2, s, kind, v=v2, variant=variant, accept_too=False),
                    self.round(3, s, "pass")], "closed", {}
        if name == "stalled":  # the same finding again, on as many records: no progress
            kind, v = ["scope", "judge"][self.stalled_seen % 2], self.vals(s)
            self.stalled_seen += 1
            variant = r.randrange(len(POOLS[kind]))
            return [self.round(k, s, kind, v=v, variant=variant, accept_too=False) for k in (1, 2)], "stalled", {}
        if name in ("limit3", "limitcap"):
            rounds, prev = [], None
            for n in range(1, 4 if name == "limit3" else 3):
                rd = self.draw(n, s, prev)
                rounds.append(rd)
                prev = rd["sig"]
            return rounds, "limit", {}
        if name == "lint":
            v = self.vals(s)
            return [], "escalated", {"c4": C_VARIANTS[r.choice([0, 1, 3])][0].format(**v)}
        if name == "escC":
            v = self.vals(s)
            return [self.round(1, s, "esc", v=v)], "escalated", {"c4": C_VARIANTS[2][0].format(**v),
                                                                  "reason": "reviewer: ESCALATE C4"}
        if name == "blocked":
            rd = self.round(1, s, "blocked")
            return [rd], "escalated", {"reason": "executor " + rd["line"]}
        raise ValueError(name)

    def tokens(self, rounds, big=False):
        r, total = self.rng, 0
        for rd in rounds:
            rd["exec_tokens"] = r.randrange(125000, 140000) if big else r.randrange(*self.exec_tokens)
            rd["review_tokens"] = r.randrange(8000, 16000) if rd["reviewed"] else 0
            total += rd["exec_tokens"] + rd["review_tokens"]
        return total


PLAN_PLANTED = {"first": 10, "ext": 3, "refs": 2, "cedit2": 2, "cedit3": 6, "limit": 14, "wdiff2": 4, "wdiff3": 2,
                "csame": 2, "ksame": 2, "escalated": 4, "dead": 4}
DEAD_REASONS = ["executor exited 1: Error: 529 overloaded, try again later",
                "executor exited 137: Killed"]
PLAN_CLEAN = {"first": 14, "fix2": 21, "fix3": 1, "shrink": 2, "limit3": 1, "limitcap": 1, "stalled": 2, "lint": 3,
              "escC": 2, "blocked": 2, "dead": 2}


def zone_ok(names, planted):
    zone = names[CUT:]
    if planted:
        stalled = [n for n in zone if n in ("wdiff2", "wdiff3", "csame", "ksame")]
        return (len(stalled) >= 8 and sum(n.startswith("wdiff") for n in zone) >= 4
                and sum(n.startswith("cedit") for n in zone) >= 5 and zone.count("limit") >= 7
                and sum(n in ("ext", "refs") for n in zone) >= 3)
    return (zone.count("stalled") == 2 and zone.count("escC") == 2 and zone.count("blocked") == 2
            and zone.count("shrink") >= 1 and zone.count("fix3") >= 1 and "limit3" in zone)


def build(planted):
    """Returns the generated records of one case: ledger rows, verdict files, contracts and the truth per round."""
    rng = random.Random(SEED + (0 if planted else 1))
    ns = None if planted else runner_namespace()
    gen = Gen(rng) if planted else CleanGen(rng, ns)
    plan = PLAN_PLANTED if planted else PLAN_CLEAN
    names = [n for n, k in plan.items() for _ in range(k)]
    for _ in range(2000):
        rng.shuffle(names)
        if zone_ok(names, planted):
            break
    else:
        raise RuntimeError("no ordering satisfies the constraints")
    clock, rows, verdicts, contracts, truth, by_run = dt.datetime(2026, 9, 1, 8, 0, 0), [], {}, {}, [], {}
    dead_seen = 0
    for i, name in enumerate(names):
        s = rng.choice(SUBJECTS)
        gen.begin()
        rounds, outcome, info = gen.scenario(name, s)
        info = info or {}
        clock += dt.timedelta(seconds=rng.randrange(20 * 3600, 52 * 3600))
        started = clock.strftime("%Y-%m-%dT%H:%M:%SZ")
        run = "r" + clock.strftime("%Y%m%d%H%M%S")
        if outcome == "dead":
            tokens, seconds = rng.randrange(2000, 9000), rng.randrange(5, 45)
            if not planted:
                info["reason"] = DEAD_REASONS[dead_seen % len(DEAD_REASONS)]
                dead_seen += 1
        elif name == "lint":
            tokens, seconds = 0, rng.randrange(1, 4)
        else:
            tokens = gen.tokens(rounds, big=name == "limitcap")
            seconds = 20 + sum(rng.randrange(110, 380) for _ in rounds)
        by_run[run] = rounds
        entry_rounds = []
        for rd in rounds:
            e = {"n": rd["n"], "touched": rd["touched"], "checks": rd["checks"]}
            if not planted and "exec_tokens" in rd:
                e.update({"exec_tokens": rd["exec_tokens"], "review_tokens": rd["review_tokens"]})
            if planted:
                e.update({"primary": rd["verdict"], "second": rd["second"]})
            else:
                e["verdict"] = rd["verdict"]
            e["failed"] = rd["failed"]
            entry_rounds.append(e)
            if rd["cat"]:
                truth.append((run, rd["n"], rd["cat"]))
            if i >= CUT:
                if planted:
                    text = (f"## checks\n{rd['check_text']}\n\n## primary\n{rd['primary_text']}\n"
                            f"## second\n{rd['second_text'] or '(not run)'}\n")
                else:
                    text = rd["file"]
                verdicts[f"{run}-r{rd['n']}.md"] = text
        row = {"run": run, "ticket": s[0], "started": started, "outcome": outcome}
        if not planted:
            crit = [("C1", "Every file under pack/ parses and each record has `id` and `name`."), ("C2", s[4]),
                    ("C3", "Every item's `parent` names a group that exists."),
                    ("C4", info.get("c4") or "No record outside the ticket's scope differs from the input."),
                    ("C5", "The unit tests under tests/ pass.")]
            scope = ["--file", s[2], "--field", s[3]] + [a for k in ALSO.get(s[0], []) for a in ("--field", k)]
            contract = {"ticket": s[0], "goal": s[1], "criteria": [{"id": a, "text": b} for a, b in crit],
                        "checks": [{"name": "schema", "criterion": "C1"}, {"name": "refs", "criterion": "C3"},
                                   {"name": "fields", "criterion": "C2", "args": ["--file", s[2], "--field", s[3]]},
                                   {"name": "scope", "criterion": "C4", "args": scope},
                                   {"name": "accept", "criterion": "C5"}]}
            body = json.dumps(contract, indent=2)
            contracts[f"{run}.json"] = body
            row["contract_sha"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
            problems = ns["lint"](contract, KNOWN)
            assert bool(problems) == (name == "lint"), (name, problems)
            if problems:
                info["reason"] = "contract lint: " + "; ".join(problems)
            if outcome == "closed":
                row["pack_sha"] = hashlib.sha256(f"{run}:pack".encode("utf-8")).hexdigest()
            if info.get("reason"):
                row["reason"] = info["reason"]
        row.update({"rounds": entry_rounds, "tokens": tokens, "seconds": seconds})
        if planted:
            row.update({"status": "ok", "lesson": rounds[-1]["lesson"] if rounds else ""})
        rows.append(row)
    if planted:
        check_shape(rows, verdicts, truth)
    else:
        check_clean(rows, by_run, ns)
    return {"rows": rows, "verdicts": verdicts, "contracts": contracts, "truth": truth, "names": names}


def check_shape(rows, verdicts, truth):
    """The generator's own guard for the planted case: the records must have the shape the answer key describes."""
    pairs = passed = 0
    for r in rows:
        for a, b in zip(r["rounds"], r["rounds"][1:]):
            if a["failed"]:
                pairs += 1
                passed += not b["failed"] and b["primary"] == "pass"
        for a, b in zip(r["rounds"], r["rounds"][1:]):
            if a["failed"] and b["failed"] and a["failed"] == b["failed"]:
                assert r["outcome"] == "stalled" and b is r["rounds"][-1], r["run"]
        if r["outcome"] == "stalled":
            assert r["rounds"][-1]["failed"] == r["rounds"][-2]["failed"], r["run"]
    cats = [c for run, n, c in truth if f"{run}-r{n}.md" in verdicts]
    closed = [r for r in rows if r["outcome"] == "closed"]
    only_contract = [r for r in closed if r["rounds"][-1]["touched"] == ["contract.json"]]
    assert passed / pairs < 0.2, passed / pairs
    assert sum(c in "CK" for c in cats) / len(cats) >= 0.6
    assert len(only_contract) / len(closed) >= 0.3


def check_clean(rows, by_run, ns):
    """The same guard for the clean case. What the runner would have done, round by round, is decided by the
    runner's own `stalled`, so the ledger cannot say `stalled`, `limit` or `closed` where the code would not."""
    pairs = passed = 0
    for r in rows:
        rds = by_run[r["run"]]
        for a, b in zip(rds, rds[1:]):
            if a["failed"]:
                pairs += 1
                passed += not b["failed"] and b["verdict"] == "pass"
            if a["verdict"] in ("fail", "skipped") and b["verdict"] in ("fail", "skipped"):
                repeat = ns["stalled"](a["sig"], b["sig"])
                assert repeat == (r["outcome"] == "stalled" and b is rds[-1]), r["run"]
        if r["outcome"] == "stalled":
            assert ns["stalled"](rds[-2]["sig"], rds[-1]["sig"]), r["run"]
        if r["outcome"] == "closed":
            assert rds[-1]["verdict"] == "pass" and "pack_sha" in r, r["run"]
        else:
            assert "pack_sha" not in r, r["run"]
        assert ("reason" in r) == (r["outcome"] in ("escalated", "dead")), r["run"]
        if r["outcome"] != "dead":
            assert sum(e["exec_tokens"] + e["review_tokens"] for e in r["rounds"]) == r["tokens"], r["run"]
        if r["outcome"] == "escalated" and not rds:
            assert r["tokens"] == 0 and r["reason"].startswith("contract lint"), r["run"]
    assert passed / pairs >= 0.75, passed / pairs
    assert not any("contract.json" in e["touched"] for r in rows for e in r["rounds"])
    over = [r for r in rows if r["tokens"] >= CAP]
    assert all(r["outcome"] == "limit" for r in over) and over


def emit(base, planted):
    data = build(planted)
    out = pathlib.Path(base)
    write(out / "docket" / "run.py", RUN_PLANTED if planted else RUN_CLEAN)
    write(out / "docket" / "release.py", RELEASE_PY if planted else RELEASE_CLEAN)
    write(out / "docket" / "precheck.py", PRECHECK_PLANTED if planted else PRECHECK_CLEAN)
    write(out / "hooks" / "gate_release.py", GATE_PLANTED if planted else GATE_CLEAN)
    if not planted:
        write(out / "docket" / "stats.py", STATS_CLEAN)
        write(out / "docket" / "ledger.py", LEDGER_PY)
        write(out / "checks" / "fields.py", FIELDS_PY)
        write(out / "checks" / "scope.py", SCOPE_PY)
    write(out / "checks" / "schema.py", SCHEMA_PY if planted else SCHEMA_CLEAN)
    write(out / "checks" / "refs.py", REFS_PY)
    write(out / "checks" / "accept.py", ACCEPT_PLANTED if planted else ACCEPT_CLEAN)
    write(out / "prompts" / "execute.md", EXECUTE_PLANTED if planted else EXECUTE_CLEAN)
    write(out / "prompts" / "review.md", REVIEW_PLANTED if planted else REVIEW_CLEAN)
    write(out / "tickets" / "EXAMPLE.json", EXAMPLE_TICKET if planted else EXAMPLE_CLEAN)
    write(out / "README.md", README_PLANTED if planted else README_CLEAN)
    write(out / "records" / "ledger.jsonl", "".join(json.dumps(r) + "\n" for r in data["rows"]))
    for name, text in data["verdicts"].items():
        write(out / "records" / "verdicts" / name, text)
    for name, text in data["contracts"].items():
        write(out / "contracts" / name, text)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    out = pathlib.Path(sys.argv[1])
    emit(out / "process-planted", True)
    emit(out / "process-clean", False)
    print(f"built {out / 'process-planted'} and {out / 'process-clean'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
