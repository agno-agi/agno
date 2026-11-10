Goal: Thoroughly test and validate `cookbook/08_learning` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for learning store examples)

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Spawn a parallel agent for each subdirectory under `cookbook/08_learning/`. Each agent handles one subdirectory independently.

3. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/08_learning/<SUBDIR>` and fix any violations.
   b. Run all `*.py` files in that subdirectory using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.
   e. Make only minimal, behavior-preserving edits where needed for style compliance.
   f. Update `cookbook/08_learning/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file.

4. After all agents complete, collect and merge results.

Special cases:
- Most learning examples require a database for storing learned knowledge — ensure pgvector is running.
- `08_custom_stores/` may use alternative storage backends — skip if dependencies are unavailable.
- `06_quick_tests/` contains lightweight validation scripts that should run quickly.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/08_learning/<SUBDIR>` (for each subdirectory)
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `00_quickstart` | `quickstart.py` | PASS | Learning store initialized and queried |
| `02_user_profile` | `user_profile.py` | PASS | User preferences stored and retrieved |
