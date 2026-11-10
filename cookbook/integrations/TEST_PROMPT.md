Goal: Thoroughly test and validate `cookbook/integrations` so it aligns with our cookbook standards.

Context files (read these first):
- `CLAUDE.md` / `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow` (Parallel needs `PARALLEL_API_KEY`)
- Database: `./cookbook/scripts/run_pgvector.sh` (for examples that persist memory or knowledge)

Execution requirements:
1. **Read every `.py` file** in the target directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to catch issues the automated checker might miss (imports inside sections, stale model references in comments, inconsistent patterns).

2. Handle each subdirectory under `cookbook/integrations/` (`parallel/`, `surrealdb/`) independently, including nested subdirectories.

3. For each subdirectory:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/integrations/<SUBDIR> --recursive` and fix any violations.
   b. Run all `*.py` files using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Update `TEST_LOG.md` in each directory with fresh PASS/FAIL entries per file.

Special cases:
- `parallel/` requires `PARALLEL_API_KEY` and `pip install parallel-web`. Task and Monitor examples can be slow (deep research runs up to ~25 minutes) — allow long timeouts or SKIP with a note.
- `parallel/09_agent_os_app.py` starts an AgentOS server — confirm it boots, then terminate.
- `surrealdb/` examples require a running SurrealDB instance — skip if not available.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/integrations/<SUBDIR> --recursive` (for each subdirectory)
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `parallel` | `01_quickstart.py` | PASS | Search returned results |
| `surrealdb` | `memory_creation.py` | SKIP | SurrealDB not running |
