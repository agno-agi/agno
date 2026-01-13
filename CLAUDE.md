# CLAUDE.md — Agno

Instructions for Claude Code when working on this codebase.

---

## Repository Structure

```
agno/
├── libs/agno/agno/          # Core framework code
├── cookbook/                # Examples, patterns and test cases (organized by topic)
├── scripts/                 # Development and build scripts
├── projects/                # Design documents (symlinked, private)
└── .cursorrules             # Coding patterns and conventions
```

---

## Testing Cookbooks

Apart from implementing features, your most important task will be to test and maintain the cookbooks in `cookbook/` directory.

> See `cookbook/15_learning/` for the golden standard.

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
- `CLAUDE.md` — Project-specific instructions (most cookbooks won't have this yet).
- `TESTING.md` — Test results log.

When testing a cookbook folder, first check for the `CLAUDE.md` file. If it doesn't exist, ask the user if they'd like you to create it. Use `cookbook/15_learning/CLAUDE.md` as a reference.

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

**3. Updating TESTING.md**

After each test, update the cookbook's `TESTING.md` with:
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

## Design Documents

The `projects/` folder contains design documents for ongoing initiatives. If you're working on one of the following projects:
- `projects/learning-machine/` — Unified learning system for agents

**Always read the design document first**.

Each project follows this structure:
```
projects/<project-name>/
├── CLAUDE.md           # Project-specific instructions (read this first)
├── design.md           # The specification
├── implementation.md   # Current status and what's done
├── decisions.md        # Why decisions were made
└── future-work.md      # What's deferred
```

**Workflow:**
1. Read the project's `CLAUDE.md` for specific instructions
2. Read `design.md` to understand what we're building
3. Check `implementation.md` for current status
4. Find the relevant code in `libs/agno`
5. Create/update cookbooks to test patterns

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

```bash
# Run a cookbook example
python cookbook/03_agents/basic.py

# Run tests
pytest libs/agno/tests/

# Run a specific test file
pytest libs/agno/tests/unit/test_agent.py
```

---

## When Implementing Features

1. **Check for design doc** in `projects/` — if it exists, follow it
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

---

## Don't

- Don't implement features without checking for a design doc first
- Don't use f-strings for print lines where there are no variables
- Don't use emojis in examples and print lines
- Don't skip async variants of public methods
- Don't push code without running `./scripts/format.sh` and `./scripts/validate.sh`
