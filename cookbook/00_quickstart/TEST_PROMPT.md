Goal: Thoroughly test and validate `cookbook/00_quickstart` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for knowledge agent)

Execution requirements:

1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart` and fix any violations.

3. Run all `cookbook/00_quickstart/*.py` examples using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`. For `run.py`, validate startup only (it's a long-running server).

4. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
   - Module docstring with `=====` underline
   - Section banners: `# ---------------------------------------------------------------------------`
   - Imports between docstring and first banner
   - `if __name__ == "__main__":` gate
   - No emoji characters

5. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.

6. Make only minimal, behavior-preserving edits where needed for style compliance.

7. Update `cookbook/00_quickstart/TEST_LOG.md` with fresh PASS/FAIL entries per file.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart`
- `source .venvs/demo/bin/python && ./scripts/format.sh` — format all code (ruff format)
- `source .venvs/demo/bin/python && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| File | Status | Notes |
|------|--------|-------|
| `agent_with_tools.py` | PASS | Produced investment brief for NVDA |
| `agent_with_storage.py` | FAIL | SQLite lock error on concurrent access |
