# Example report

What a setup review returns, unedited. It was run on 2026-11-27 with plugin
2.1.0, headless, on `claude-sonnet-5-5`, against the `planted` calibration
setup that [evals/build_fixtures.py](../evals/build_fixtures.py) builds: a
small billing-service project with ten defects placed on purpose and an
answer key in [evals/ANSWER-KEY.md](../evals/ANSWER-KEY.md).

```bash
python evals/build_fixtures.py <new empty directory>
cd <new empty directory>/planted/project
claude -p "/grade-optimizer:grade-optimizer Review the Claude Code setup whose user-level directory is <dir>/planted/home/.claude and whose project is <dir>/planted/project. Do not change anything. Write the full report to the terminal, in English." \
  --plugin-dir <this repository> --model sonnet \
  --allowedTools "Read,Glob,Grep,Bash(python *),Bash(python3 *),Bash(py *)" \
  --disallowedTools "Edit,Write"
```

Scored against the key, this run found all ten planted defects (D1 to D10)
and each of its nine findings corresponds to one of them, so none is false by
the key. Every claim id it cites exists in the knowledge base. The figures
and asides inside the findings were not checked one by one. One run is one sample; [evals/README.md](../evals/README.md)
has the rounds and how they are scored. Only local paths were replaced
(`<project>`, `<fixture>`, `<tmp>`); the text is otherwise as the reviewer
wrote it, including its phrasing slips.

The usage figures (requests, cache, spawns) come from the session history the
builder generates for the fixture, not from a real user.

---

# Grade review: billing-service setup (Sonnet 5.5, read-only)

The project's one critical rule, "never push to main", is enforced nowhere. The hook meant to block it exits with code 1, which lets the action through. There are also two smaller problems. `audit-readonly` claims a safety it doesn't provide, and one agent has a typo that quietly changes its model.

Nothing was changed. This is the report you asked for, in English.

## Measured picture

| Item | Value |
|---|---|
| Fixed context per session | about 508 tokens (CLAUDE.md about 322, skill listing about 139, agent listing about 47) |
| Main-session load | 100 requests on `claude-opus-5-5` at medium effort, average prompt about 84k tokens |
| Cache | 97.6% of prompt tokens are cache reads; 0 cache rebuilds detected |
| Agent spawns | 29 total: 23 generic (no definition here), 6 `renamer`, 0 `helper` |
| Skills invoked | `deploy-staging` ×8, `repo-stats` ×3, `audit-readonly` ×1, `release-staging` ×0 |

The fixed cost is tiny, so trimming instruction files would not move anything. The cost sits in conversation growth (84k per request), which is outside this setup's files.

## Findings, largest first

### 1. The main-push guard fails open
- **Where:** `home/.claude/hooks/guard_main.py` (`sys.exit(1)`), registered as PreToolUse on Bash in `settings.json`.
- **Problem:** The script prints "Pushing to main is not allowed" and exits 1. On PreToolUse, exit 1 without JSON lets the action proceed, and only exit 2 blocks. The project CLAUDE.md states the rule in prose with three emphasis markers. So the rule is a request in CLAUDE.md and a warning in the hook, and nothing stops the push.
- **Matching gaps (judgment):**
  - `"git push" in command and "main" in command` also blocks harmless commands such as `git push origin domain-fix`.
  - It misses `git push` or `git push origin HEAD` while main is checked out, and `git -C <dir> push`.
- **Basis:** hooks-001, quote: "If your hook is meant to enforce a policy, use `exit 2`." Also harness-002: "An instruction like "never edit `.env`" in CLAUDE.md or a skill is a request, not a guarantee."
- **Change:**
  1. Replace `sys.exit(1)` with `sys.exit(2)`.
  2. Tighten the match: split the command on `&&`, `;` and `|`, and use a regex like `\bgit\b.*\bpush\b`.
  3. Block when a token is `main`, `master`, `HEAD:main` or `refs/heads/main`.
  4. Also block when the push has no explicit branch and `git branch --show-current` returns `main`.
  5. Add `"onFailure": "block"` to the hook entry, so a crash or timeout also blocks (hooks-005; it needs a recent Claude Code version, so check yours).
- **Cost:** Some legitimate pushes get blocked, and a hook crash stops Bash work until fixed. Server-side branch protection on `main` is the only guarantee that also covers pushes made outside Claude. I couldn't see that setting from here.
- **Confidence:** high on the exit code, because the documentation is explicit. To test it, run `git push origin main` in a sandbox repo and confirm the tool call is denied.
- **How to tell it worked:** The call is refused, where today it runs.

### 2. The CLAUDE.md emphasis around the push rule can go once the hook blocks
- **Where:** `project/CLAUDE.md`, the "IMPORTANT: NEVER push…" line near the top, and "CRITICAL: REMEMBER, NEVER PUSH TO MAIN!!!" at the bottom.
- **Problem:** The same rule appears twice, with emphasis, while its actual enforcement is broken. Marking several instructions as critical makes the markers less informative.
- **Basis:** prompting-018, quote: "Emphasis is not banned; it is a tested, scoped fix for one demonstrably underweighted instruction, not a first-draft register."
- **Change:** Once finding 1 is fixed, keep one plain sentence with the reason, for example "Open a PR; main is protected by a hook." Drop the capitals.
- **Cost:** Almost nothing. Keep the single sentence so the model knows why a push gets denied.
- **Confidence:** medium. It is a style effect and not measured here.

### 3. `audit-readonly` promises a read-only guarantee it doesn't give
- **Where:** `skills/audit-readonly/SKILL.md`, body text and `allowed-tools: Read, Grep, Glob`.
- **Problem:** The body says "because of `allowed-tools`, it cannot modify files or run commands, so it is safe to use on a production checkout." That is wrong. `allowed-tools` only pre-approves the listed tools for that turn, and other tools stay callable under the session's normal permissions. Someone could trust it on production because of this sentence.
- **Basis:** skills-012, quote: "The `allowed-tools` field grants permission for the listed tools during the turn that invokes the skill, so Claude can use them without prompting you for approval."
- **Change:** Delete the false sentence. If read-only really matters, add permission deny rules for `Edit`, `Write` and Bash, or use `disallowed-tools` in the skill, with the removal-until-next-message limit from skills-015.
- **Confidence:** high on the documented behavior.

### 4. `helper` agent: a typo, a vague description, and no use
- **Where:** `agents/helper.md`.
  - The key `modle: haiku` is a typo, so the agent inherits the session model (Opus here), not Haiku. The measurement shows it as `(inherits)` with an unrecognized field.
  - The description "Helps with code." gives routing nothing to match.
  - The body ("be careful and thorough") adds nothing.
  - It was never spawned. Meanwhile 23 spawns used the generic agent.
- **Change:** Delete it unless you can say in one sentence what it does that the generic agent doesn't. If you keep it, fix the key to `model:`, rewrite the description as what it does plus when to use it, and write a real brief.
- **Cost:** About 4 tokens per session, so this is hygiene more than savings. The typo matters because it hides the model you thought you had chosen.
- **Basis:** routing claims (skills-048 on descriptions) for the vague description; the typo is measured, not a claim.

### 5. `deploy-staging` and `release-staging` collide, and one can fire a deploy by itself
- **Where:** the two skills' descriptions (Jaccard 0.62, nearly the same trigger words) and bodies.
- **Problem:**
  - Both claim "deploy/release/ship to staging". The first runs three `make` targets, the second `scripts/release.sh staging`. `deploy-staging` took 8 invocations and `release-staging` took 0, so the second is dead weight and can confuse routing.
  - Both have side effects and are model-invocable, so Claude can start a staging push from a loosely worded request.
- **Basis:** skills-802 (`disable-model-invocation: true` for workflows with side effects) and the routing core claims.
- **Change:**
  1. Remove `release-staging`, or merge the two if `scripts/release.sh` does something `make` doesn't. I can't see that script, so ask before deleting.
  2. Add `disable-model-invocation: true` to the survivor, so staging deploys happen only when you type the command.
- **Cost:** Deploys stop being triggered by natural language. The 8 recent uses may have been that, so check how you invoke it before flipping the flag.
- **Confidence:** medium to high on the collision. The usage window is 30 days on one machine, so "never invoked" is a question for you.

### 6. `repo-stats` makes the model count lines by hand
- **Where:** `skills/repo-stats/SKILL.md`.
- **Problem:** It tells the model to open every file, count lines by reading, and "keep the totals in your head". That is slow, expensive in context, and error-prone, because counting is exact work. It ran 3 times.
- **Basis:** the setup-review and CLAUDE principle that a repeated step needing no judgment becomes a script (judgment, plus `references/foundations.md` on measurement).
- **Change:** Replace the body with one command, such as `cloc --by-file-by-lang .` or a short Python script that counts lines per extension. Have it print a table and let the model relay it.
- **How to tell it worked:** Each run uses far fewer tokens and the totals match the script's output.

### 7. The formatter hook points at a file that doesn't exist
- **Where:** PostToolUse on `Edit|Write` runs `python ~/.claude/hooks/format_changed.py`, and `measure.py` reports the script missing.
- **Problem:** Every edit triggers a hook that errors. Non-blocking failures are easy to ignore, so it will likely never be noticed.
- **Change:** Create the script, or remove the entry. If you create it, note that a hook on Edit and Write doesn't see shell-made changes (hooks-034). Treat formatting as best-effort, not a guarantee.
- **Confidence:** high that the file is absent. It could live elsewhere on your real machine, since this review reads a copy.

### 8. `renamer` runs at the top tier and maximum effort for mechanical work
- **Where:** `agents/renamer.md` (`model: opus`, `effort: max`).
- **Observation:** The brief is good: it counts before changing, re-searches after, and reports leftovers. But the work is applying one rule across many files. Max effort on Opus is the most expensive setting for that, and Sonnet 5.5 documents routine work at `high` or below (model-042: at `xhigh` and `max` it can start extra review rounds).
- **Experiment, not a verdict (judgment):** Move `renamer` to `sonnet` at `medium`, which is the documented start for well-specified agentic work (model-036). Keep the re-search check as the quality test. Compare cost per run once there are enough runs, because `agent_runs` is empty today and the 6 runs can't be compared.
- **Cost:** If the rename needs real judgment about edge cases, quality could drop. The after-count check would show that.

### 9. The month-end procedure in CLAUDE.md loads every session
- **Where:** `project/CLAUDE.md`, the 10-step close procedure.
- **Observation:** It has real side effects (`lock-month`, emailing finance, tagging) and is only used once a month. A procedure needed only for some tasks fits a skill better (skills-802, quote: "A long release procedure sitting in a skill doesn't weigh on your unrelated bug fix the way it would in `CLAUDE.md`."). With `disable-model-invocation: true`, it would also never run by accident.
- **Real saving:** about 150 tokens per session. This is minor, and a short pointer in CLAUDE.md is fine. I'd do it only if you want the lock and email steps to need an explicit command.
- **Confidence:** low priority, and it is your call.

## What I left alone
- **The CLAUDE.md money rule** (integer cents, `Decimal` only at the API boundary): it has a stated reason and is exactly the context only the author has.
- **`make test` and the Postgres note**: the test command is named, which gives the model a check it can run. It could add how to run one test, but nothing is wrong.
- **`renamer`'s body**: a good brief, with an explicit after-check and a defined return.
- **Settings**: `model: opus` matches what ran (`opus-5-5` at medium effort), so no model mismatch.

## Not measured
- MCP definitions and the built-in prompt (run `/context` and paste it if you have MCP servers).
- Auto memory and plugin hooks, and hooks in skill or agent frontmatter.
- Whether the skill listing exceeds its budget (probably not at about 139 tokens).
- The compaction window setting, which wasn't exposed, so I can't compare it to the 84k average.
- Subagent sessions: none were found (0 transcripts), so per-agent cost is unknown. All 29 spawns appear only as counts.
- `.claude.json` and anything above the project directory (skipped by `--no-external-reads`).
- Model-fit: I'm Sonnet 5.5 and the knowledge base covers it. I took its notes into account, including its habits of adding unrequested files and stopping early on long tasks. I leaned on measured and documented findings and avoided padding.

**Suggested next step:** fix `guard_main.py` first (finding 1), then re-run `measure.py --compare` against the saved JSON at `%TEMP%\go-measure.json` once you've applied changes.

Decision for you: should `release-staging` be deleted, or does `scripts/release.sh` do something that `deploy-staging` doesn't?
