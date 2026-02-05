# AGENTS.md — Agno

Instructions for coding agents working on this codebase.

---

## Repository Structure

```
agno/
├── libs/agno/agno/          # Core framework code
├── cookbook/                # Examples, patterns and test cases (organized by topic)
├── scripts/                 # Development and build scripts
├── specs/                   # Design documents (symlinked, private)
└── .cursorrules             # Coding patterns and conventions
```

---

## Virtual Environments

This project uses two virtual environments:

| Environment | Purpose | Setup |
|-------------|---------|-------|
| `.venv/` | Development: tests, formatting, validation | `uv sync` or standard setup |
| `.venvs/demo/` | Cookbooks: has all demo dependencies | `./scripts/demo_setup.sh` |

Use `.venv` for development tasks (`pytest`, formatting, validation).

Use `.venvs/demo` for running cookbook examples.

---

## Testing Cookbooks

Cookbooks live in `cookbook/` and should keep working.

**Test environment:**

```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Setup (if needed)
./scripts/demo_setup.sh

# Database (if needed)
./cookbook/scripts/run_pgvector.sh
```

**Run a cookbook:**

```bash
.venvs/demo/bin/python cookbook/<folder>/<file>.py
```

### Expected Cookbook Structure

Each cookbook folder should have:
- `README.md` — The README for the cookbook
- `CLAUDE.md` — project-specific instructions (optional, but preferred for complex cookbooks)
- `TEST_LOG.md` — test results log

When testing a cookbook folder, first check for `cookbook/<folder>/CLAUDE.md`. If it doesn't exist, ask the user if they'd like it created. Use `cookbook/08_learning/CLAUDE.md` as a reference.

---

## Design Documents

The `specs/` folder contains design documents for ongoing initiatives (it may be a symlink).

Each spec typically follows:

```
specs/<spec-name>/
├── CLAUDE.md           # Spec-specific instructions (read this first)
├── design.md           # The specification
├── implementation.md   # Current status and what's done
├── decisions.md        # Why decisions were made
└── future-work.md      # What's deferred
```

Workflow:
1. Read the spec’s `CLAUDE.md` (if present)
2. Read `design.md`
3. Check `implementation.md`
4. Implement in `libs/agno`
5. Add/update cookbooks or tests as appropriate

---

## Code Locations

| What | Where |
|------|-------|
| Core agent code | `libs/agno/agno/agent/` |
| Teams | `libs/agno/agno/team/` |
| Workflows | `libs/agno/agno/workflow/` |
| Tools | `libs/agno/agno/tools/` |
| Models | `libs/agno/agno/models/` |
| Knowledge/RAG | `libs/agno/agno/knowledge/` |
| Memory | `libs/agno/agno/memory/` |
| Learning | `libs/agno/agno/learn/` |
| Database adapters | `libs/agno/agno/db/` |
| Vector databases | `libs/agno/agno/vectordb/` |
| Tests | `libs/agno/tests/` |

---

## Coding Patterns

See `.cursorrules` for detailed patterns. Key rules:

- Never create agents in loops — reuse them for performance
- Use `output_schema` for structured responses
- PostgreSQL in production, SQLite for dev only
- Start with a single agent, scale up only when needed
- Maintain both sync and async variants for public APIs

---

## Running Code

**Running cookbooks:**

```bash
.venvs/demo/bin/python cookbook/<folder>/<file>.py
```

**Running tests:**

```bash
source .venv/bin/activate
pytest libs/agno/tests/

# Run a specific test file
pytest libs/agno/tests/unit/agent/test_basic.py
```

---

## When Implementing Features

1. Check for a relevant design doc in `specs/` (follow it if present)
2. Look for existing patterns in `libs/agno/agno/` and match style/conventions
3. Add a cookbook example when introducing a new pattern
4. Update the spec’s `implementation.md` when working under an active spec

---

## Before Submitting Code

Run formatting and validation:

```bash
source .venv/bin/activate
./scripts/format.sh
./scripts/validate.sh
```

Both scripts should pass with no errors.

**PR Title Format:**

PR titles must follow one of:
- `[type] description` — e.g., `[feat] add workflow serialization`
- `type: description` — e.g., `feat: add workflow serialization`
- `type-kebab-case` — e.g., `feat-workflow-serialization`

Valid types: `feat`, `fix`, `cookbook`, `test`, `refactor`, `build`, `ci`, `chore`, `perf`, `style`, `revert`

**PR Description:**

Follow the PR template in `.github/pull_request_template.md`. Include:
- Summary of changes
- Type of change (bug fix, new feature, etc.)
- Completed checklist items
- Any additional context

---

## GitHub Operations

If `gh pr edit` fails with GraphQL errors related to classic projects, use the API directly:

```bash
# Update PR body
gh api repos/agno-agi/agno/pulls/<PR_NUMBER> -X PATCH -f body="<PR_BODY>"

# Or with a file
gh api repos/agno-agi/agno/pulls/<PR_NUMBER> -X PATCH -f body="$(cat /path/to/body.md)"
```

---

## Don’t

- Don’t implement features without checking `specs/` for a relevant design doc
- Don’t use f-strings for print lines when there are no variables to format
- Don’t use emojis in examples or print lines
- Don’t skip async variants of public methods
- Don’t push code without running formatting and validation scripts
- Don’t submit a PR without a detailed description (use the PR template)
