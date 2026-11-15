# Calibration

A reviewer is worth trusting when it finds the defects that are there and does
not report ones that are not. These files measure both.

## What is here

- `build_fixtures.py` writes two throwaway Claude Code setups into a directory
  you name. `planted` has ten defects, each a specific mistake that Anthropic's
  documentation says is one. `clean` is a small setup with nothing wrong that
  matters.
- `ANSWER-KEY.md` lists the ten defects with the claims behind each, what in
  `planted` is deliberately sound, and how to score a run.

## Running it

```bash
python evals/build_fixtures.py /tmp/calibration
```

Then, in a fresh Claude Code session with this skill installed, once for each
setup:

```
Review the Claude Code setup whose user-level directory is
/tmp/calibration/planted/home/.claude and whose project is
/tmp/calibration/planted/project. Do not change anything in it.
```

The session must not be able to see `ANSWER-KEY.md` or `build_fixtures.py`: run
it from a directory outside this repository and give it only the built paths.
Score each report against the key. A run produces three numbers: defects found
out of ten on `planted`, false findings on `planted`, and findings presented as
significant on `clean`.

One run is one sample. The same model on the same setup will not produce the
same report twice, so treat a difference of one defect between two runs as
noise, and repeat before concluding that a change to a guide helped or hurt.

## Recorded results

Each row is a single run, scored by hand against the key.

| Date | Skill version | Model | Found on `planted` | False on `planted` | Significant on `clean` |
|---|---|---|---|---|---|
