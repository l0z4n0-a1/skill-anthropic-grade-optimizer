# Security Policy

## Supported versions

Only the latest minor version of `anthropic-grade-optimizer` receives security
fixes.

| Version | Supported |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ |

## Reporting a vulnerability

If you discover a security issue — for example, a path-traversal in the
artifact ingestion, an injection in the Pass-2 prompt construction, or any
way to coerce the auditor into emitting fabricated rule citations — please
**do not** open a public GitHub issue.

Instead, email the maintainer at **fluxmind.ia@gmail.com** with:

- A short description of the issue and impact.
- A minimal reproduction (artifact path, command, observed behavior).
- Your suggested mitigation, if you have one.

You can expect an acknowledgment within 7 days. Coordinated disclosure is
preferred; the maintainer will work with you on a release timeline before
any public disclosure.

## Threat model (in scope)

- The auditor runs **locally** on operator-trusted machines.
- `--pass2` sends the audited artifact and rules block to the Anthropic API.
  Do not run `--pass2` on artifacts containing secrets you would not paste
  into the Claude API.
- The orchestrator never executes the artifact under audit; it reads it as
  text and pattern-matches against deterministic detectors.

## Out of scope

- Vulnerabilities in third-party dependencies (`pyyaml`, `pytest`,
  `anthropic` SDK) — please report those upstream.
- Misconfiguration on the operator side (running on untrusted artifacts,
  exposing `ANTHROPIC_API_KEY`, etc.).
