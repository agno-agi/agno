# AGENTS.md — Agno

Instructions for coding agents working on this codebase (Codex CLI, Claude Code, etc.).

## Repository Structure

```
agno/
├── libs/agno/agno/          # Core framework code
├── cookbook/                # Examples, patterns and test cases (organized by topic)
├── scripts/                 # Development and build scripts
├── specs/                   # Design documents (symlinked, private)
└── .cursorrules             # Coding patterns and conventions
```

## Virtual Environments

This project uses two virtual environments:

| Environment | Purpose | Setup |
|-------------|---------|-------|
| `.venv/` | Development: tests, formatting, validation | `uv sync` (or standard setup) |
| `.venvs/demo/` | Cookbooks: has all demo dependencies | `./scripts/demo_setup.sh` |

- Use `.venv` for development tasks (`pytest`, `./scripts/format.sh`, `./scripts/validate.sh`).
- Use `.venvs/demo` for running cookbook examples.

## Testing Cookbooks

Apart from implementing features, the most important work is testing and maintaining the cookbooks in `cookbook/`.

See `cookbook/08_learning/` for the gold standard.

### Quick Reference

```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Setup (if needed)
./scripts/demo_setup.sh

# Database (if needed)
./cookbook/scripts/run_pgvector.sh
```

Run a cookbook:
```bash
.venvs/demo/bin/python cookbook/<folder>/<file>.py
```

### Expected Cookbook Structure

Each cookbook folder should have:
- `README.md`
- `CLAUDE.md` (optional; cookbook-specific instructions)
- `TEST_LOG.md` (test results log)

When testing a cookbook folder, check for `CLAUDE.md` first. If it doesn't exist, ask if one should be created (use `cookbook/08_learning/CLAUDE.md` as reference).

### Updating `TEST_LOG.md`

After each test, append:

```markdown
### filename.py

**Status:** PASS/FAIL

**Description:** What the test does and what was observed.

**Result:** Summary of success/failure.

---
```

## Design Documents

The `specs/` folder contains design documents for ongoing initiatives.

Workflow:
1. Read the spec’s `CLAUDE.md` (if present)
2. Read `design.md` to understand what we’re building
3. Check `implementation.md` for current status
4. Find relevant code in `libs/agno`
5. Create/update cookbooks to test patterns

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

## Coding Patterns

See `.cursorrules` for detailed patterns. Key rules:

- Never create agents in loops — reuse them for performance
- Use `output_schema` for structured responses
- PostgreSQL in production; SQLite for dev only
- Start with single agent; scale up only when needed
- Implement both sync and async variants for public methods

## Running Code

Run tests:
```bash
source .venv/bin/activate
pytest libs/agno/tests/
```

Run a specific test:
```bash
pytest libs/agno/tests/unit/test_agent.py
```

## Before Submitting Code

Always run:
```bash
source .venv/bin/activate
./scripts/format.sh
./scripts/validate.sh
```

Both scripts must pass.

## GitHub Operations

If `gh pr edit` fails with GraphQL errors related to classic projects, use the API directly:

```bash
gh api repos/agno-agi/agno/pulls/<PR_NUMBER> -X PATCH -f body="<PR_BODY>"
```

## Don’t

- Don’t implement features without checking for a relevant design doc first
- Don’t use f-strings for print lines where there are no variables
- Don’t use emojis in examples or print lines
- Don’t skip async variants of public methods
- Don’t push code without running `./scripts/format.sh` and `./scripts/validate.sh`
