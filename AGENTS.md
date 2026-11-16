# Working on text-to-sql-guardrails

These rules are for anyone changing this repo, human or agent.

## Commands
- Set up: `uv sync`
- Test: `uv run pytest && uv run ruff check .`

## Rules
1. **One change, one complete commit.** Code, tests and docs for a change go in the
   same commit. Mention the issue it belongs to (`Refs #12`, `Closes #12`).
2. **Prove it works.** Run the tests before saying something is done and show the output.
   No test for it yet? Add one.
3. **Write decisions down.** Anything non-obvious (a library choice, a trade-off, a dead end)
   goes in `DECISIONS.md` with the date and the reason.
4. **Keep the changelog.** User-visible changes go under "Unreleased" in `CHANGELOG.md`.
5. **Small steps.** Prefer several small working commits over one big one.
