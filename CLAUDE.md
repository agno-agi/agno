# CLAUDE.md — Agno

Instructions for Claude Code when working on this codebase.

---

## Repository Structure

```
agno/
├── libs/agno/agno/          # Core framework code
├── cookbook/                 # Examples and patterns (organized by topic)
├── scripts/                  # Development and build scripts
├── projects/                 # Design documents (symlinked, private)
└── .cursorrules             # Coding patterns and conventions
```

---

## Design Documents

The `projects/` folder contains design documents for ongoing initiatives. **Always check here first** when working on a feature.

Each project follows this structure:
```
projects/<project-name>/
├── CLAUDE.md           # Project-specific instructions (read this first)
├── design.md           # The specification
├── implementation.md   # Current status and what's done
├── decisions.md        # Why decisions were made
└── future-work.md      # What's deferred
```

**Current projects:**
- `projects/learning-machine/` — Unified learning system for agents

**Workflow:**
1. Read the project's `CLAUDE.md` for specific instructions
2. Read `design.md` to understand what we're building
3. Check `implementation.md` for current status
4. Find the relevant code in `libs/agno/agno/`
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

## Don't

- Don't implement features without checking for a design doc first
- Don't use f-strings for print lines where there are no variables
- Don't use emojis in examples and print lines
- Don't skip async variants of public methods
