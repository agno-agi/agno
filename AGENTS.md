# AGENTS.md — Agno

Instructions for coding agents working in this repository.

These instructions apply to the entire repo unless a more specific `AGENTS.md` exists in a subdirectory.

## Repository layout

- Core framework: `libs/agno/agno/`
- Cookbooks (examples/patterns): `cookbook/`
- Dev/build scripts: `scripts/`
- Design docs (may be symlinked/private): `specs/`
- Conventions: `.cursorrules`

## Virtual environments

This repo typically uses two virtual environments:

- **Development** (`.venv/`): run `pytest`, formatting, validation (`uv sync` or standard setup).
- **Cookbooks** (`.venvs/demo/`): has demo dependencies; set up with `./scripts/demo_setup.sh`.

Guidance:
- Use **dev env** for code-quality + tests: `source .venv/bin/activate` (or the project’s configured dev venv).
- Use **demo env** for running cookbooks: `.venvs/demo/bin/python cookbook/<path>.py`.

## Cookbooks are first-class

When you touch `cookbook/`:
- Prefer runnable, well-documented examples.
- Each cookbook folder should have:
  - `README.md`
  - `TEST_LOG.md`
  - optional `CLAUDE.md` (folder-specific guidance)
- If a cookbook folder lacks `CLAUDE.md` and you’re doing significant work there, ask whether to create it (use `cookbook/08_learning/CLAUDE.md` as a reference).
- After running a cookbook, append a short entry to that folder’s `TEST_LOG.md` (PASS/FAIL + what was tested).

Quick commands:
```bash
./scripts/demo_setup.sh
.venvs/demo/bin/python cookbook/<folder>/<file>.py
./cookbook/scripts/run_pgvector.sh   # if needed
```

## Specs / design docs

If the feature you’re working on has a spec under `specs/`:
1. Read `specs/<spec-name>/CLAUDE.md` first
2. Read `design.md`, then `implementation.md`
3. Follow existing patterns in `libs/agno/`
4. Add/adjust cookbooks to demonstrate + test the pattern

## Coding patterns (high-level)

- Avoid creating `Agent` instances in loops; reuse agents for performance.
- Public APIs should generally have both sync and async variants.
- Prefer `output_schema` for structured responses.
- Assume PostgreSQL in production; use SQLite for local/dev only.
- Start with a single agent; scale to teams/workflows only when needed.
- Follow `.cursorrules` for style and conventions.

## Before submitting

Run the repo scripts from the dev environment:
```bash
source .venv/bin/activate
./scripts/format.sh
./scripts/validate.sh
pytest libs/agno/tests/
```

