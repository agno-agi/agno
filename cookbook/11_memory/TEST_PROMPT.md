Goal: Thoroughly test and validate `cookbook/11_memory` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for memory persistence)

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Test root-level files and each subdirectory. Spawn a parallel agent for `memory_manager/` and `optimize_memories/` if desired.

3. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory/<SUBDIR>` and fix any violations.
   b. Run all `*.py` files using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.
   e. Make only minimal, behavior-preserving edits where needed for style compliance.
   f. Update `cookbook/11_memory/TEST_LOG.md` (root), `cookbook/11_memory/memory_manager/TEST_LOG.md`, and `cookbook/11_memory/optimize_memories/TEST_LOG.md` with fresh PASS/FAIL entries per file.

4. After all agents complete, collect and merge results.

Special cases:
- All memory examples require a running PostgreSQL instance — ensure `./cookbook/scripts/run_pgvector.sh` is running.
- `05_multi_user_multi_session_chat.py` and `06_multi_user_multi_session_chat_concurrent.py` simulate multi-user sessions — they may take longer.
- `memory_manager/` files use the MemoryManager API directly (not through Agent) — they have different patterns from root-level files.
- `memory_manager/surrealdb/` files are being relocated to `cookbook/92_integrations/surrealdb/` — skip if still present.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory`
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory/memory_manager`
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/11_memory/optimize_memories`
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| root | `01_agent_with_memory.py` | PASS | Memory persisted across runs |
| `memory_manager` | `01_standalone_memory.py` | PASS | CRUD operations completed |
