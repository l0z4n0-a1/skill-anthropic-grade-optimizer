---
name: good-skill-example
description: Validates Markdown documents for broken links, missing alt-text on images, and TOC drift against actual headings. Use when the user asks to lint markdown, check for broken links, verify image accessibility, or audit documentation hygiene; phrases like "check my markdown", "find broken links", "validate this README" all trigger this skill.
when_to_use: User asks to validate, lint, or audit markdown files. User mentions broken links, missing alt-text, accessibility checks, or TOC consistency.
---

# Good Skill Example

A clean, Anthropic-canonical skill for markdown validation. Designed to score A on self-audit.

## Quick Start

Run `python scripts/check.py <file.md>` to validate a single file. Output is JSON with findings array.

## How It Works

The skill applies three deterministic checks, then optionally runs a qualitative pass:

1. Parse markdown to extract links, images, headings.
2. For each link, verify target exists (local file or HTTP HEAD).
3. For each image, check alt-text presence.
4. Compare TOC entries against actual heading structure.

## When This Skill Helps

When you have markdown files where stale links accumulate, accessibility regressions slip in, or TOC entries drift from the actual headings. Particularly useful before publishing documentation.

## When This Skill Does Not Apply

Non-markdown formats (RST, AsciiDoc) require different parsers and are out of scope.
