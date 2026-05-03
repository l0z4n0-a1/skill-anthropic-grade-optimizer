# CLAUDE.md (good fixture — should score A)

Concise, fact-oriented project memory. Designed to pass all hard rules.

## Build & Test

- Use `npm test` to run the test suite.
- Run `npm run lint` before committing.
- API handlers live in `src/api/handlers/`.

## Code Conventions

- Use 2-space indentation.
- Prefer named exports over default exports.
- All async functions must include explicit error handling.

## Architecture Notes

- The router uses path-based dispatch in `src/router.ts`.
- Database migrations live in `db/migrations/` and run automatically on startup.
- Environment variables are loaded from `.env.local` (gitignored).

## Important Constraints

The auth flow uses signed cookies; YOU MUST not log cookie values in any environment. Always use the `redactCookie` helper before any log statement that touches the auth payload.
