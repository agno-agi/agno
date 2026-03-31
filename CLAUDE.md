# CLAUDE.md — Agno

Instructions for Claude Code when working on this codebase.

---

## Repository Structure

```
.
├── libs/agno/agno/          # Core framework code
├── cookbook/                # Examples, patterns and test cases (organized by topic)
├── scripts/                 # Development and build scripts
├── specs/                   # Design documents (symlinked, private)
├── docs/                    # Documentation (symlinked, private)
└── .cursorrules             # Coding patterns and conventions
```

---

## Conductor Notes

When working in Conductor, you can use the `.context/` directory for scratch notes or agent-to-agent handoff artifacts. This directory is gitignored.

---

## Setting Up Symlinks

The `specs/` and `docs/` directories are symlinked from external locations. For a fresh clone or new workspace, create these symlinks:

```bash
ln -s ~/code/specs specs
ln -s ~/code/docs docs
```

These contain private design documents and documentation that are not checked into the repository.

---

## Virtual Environments

This project uses two virtual environments:

| Environment | Purpose | Setup |
|-------------|---------|-------|
| `.venv/` | Development: tests, formatting, validation | `./scripts/dev_setup.sh` |
| `.venvs/demo/` | Cookbooks: has all demo dependencies | `./scripts/demo_setup.sh` |

**Use `.venv`** for development tasks (`pytest`, `./scripts/format.sh`, `./scripts/validate.sh`).

**Use `.venvs/demo`** for running cookbook examples.

---

## Testing Cookbooks

Apart from implementing features, your most important task will be to test and maintain the cookbooks in `cookbook/` directory.

> See `cookbook/08_learning/` for the golden standard.

### Quick Reference

**Test Environment:**

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

Each cookbook folder should have the following files:
- `README.md` — The README for the cookbook.
- `TEST_LOG.md` — Test results log.

### Testing Workflow

**1. Before Testing**
- Ensure the virtual environment exists (run `./scripts/demo_setup.sh` if needed)
- Start any required services (e.g., `./cookbook/scripts/run_pgvector.sh`)

**2. Running Tests**
```bash
# Run individual cookbook
.venvs/demo/bin/python cookbook/<folder>/<file>.py

# Tail output for long tests
.venvs/demo/bin/python cookbook/<folder>/<file>.py 2>&1 | tail -100
```

**3. Updating TEST_LOG.md**

After each test, update the cookbook's `TEST_LOG.md` with:
- Test name and path
- Status: PASS or FAIL
- Brief description of what was tested
- Any notable observations or issues

Format:
```markdown
### filename.py

**Status:** PASS/FAIL

**Description:** What the test does and what was observed.

**Result:** Summary of success/failure.

---
```

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

- **Never create agents in loops** — reuse them for performance
- **Use output_schema** for structured responses
- **PostgreSQL in production**, SQLite for dev only
- **Start with single agent**, scale up only when needed
- **Both sync and async** — all public methods need both variants

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
pytest libs/agno/tests/unit/test_agent.py
```

---

## When Implementing Features

1. **Check for design doc** in `specs/` — if it exists, follow it
2. **Look at existing patterns** — find similar code and follow conventions
3. **Create a cookbook** — every pattern should have an example
4. **Update implementation.md** — mark what's done

---

## Before Submitting Code

**Always run these scripts before pushing code or creating a PR:**

```bash
# Activate the virtual environment first
source .venv/bin/activate

# Format all code (ruff format)
./scripts/format.sh

# Validate all code (ruff check, mypy)
./scripts/validate.sh
```

Both scripts must pass with no errors before code review.

**PR Title Format:**

PR titles must follow one of these formats:
- `type: description` — e.g., `feat: add workflow serialization`
- `[type] description` — e.g., `[feat] add workflow serialization`
- `type-kebab-case` — e.g., `feat-workflow-serialization`

Valid types: `feat`, `fix`, `cookbook`, `test`, `refactor`, `chore`, `style`, `revert`, `release`

**PR Description:**

Always follow the PR template in `.github/pull_request_template.md`. Include:
- Summary of changes
- Type of change (bug fix, new feature, etc.)
- Completed checklist items
- Any additional context

---

## GitHub Operations

**Updating PR descriptions:**

The `gh pr edit` command may fail with GraphQL errors related to classic projects. Use the API directly instead:

```bash
# Update PR body
gh api repos/agno-agi/agno/pulls/<PR_NUMBER> -X PATCH -f body="<PR_BODY>"

# Or with a file
gh api repos/agno-agi/agno/pulls/<PR_NUMBER> -X PATCH -f body="$(cat /path/to/body.md)"
```

---

## Don't

- Don't implement features without checking for a design doc first
- Don't use f-strings for print lines where there are no variables
- Don't use emojis in examples and print lines
- Don't skip async variants of public methods
- Don't push code without running `./scripts/format.sh` and `./scripts/validate.sh`
- Don't submit a PR without a detailed PR description. Always follow the PR template provided in `.github/pull_request_template.md`.

---

## CI: Automated Code Review

Every non-draft PR automatically receives a review from Opus using both `code-review` and `pr-review-toolkit` official plugins (10 specialized agents total). No manual trigger needed — the review posts as a sticky comment on the PR.

When running in GitHub Actions (CI), always end your response with a plain-text summary of findings. Never let the final action be a tool call. If there are no issues, say "No high-confidence findings."

Agno-specific checks to always verify:
- Both sync and async variants exist for all new public methods
- No agent creation inside loops (agents should be reused)
- CLAUDE.md coding patterns are followed
- No f-strings for print lines where there are no variables
