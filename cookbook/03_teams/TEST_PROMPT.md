Goal: Thoroughly test and validate `cookbook/03_teams` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for knowledge, session, distributed_rag examples)

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Spawn a parallel agent for each subdirectory under `cookbook/03_teams/`. Each agent handles one subdirectory independently.

3. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/03_teams/<SUBDIR>` and fix any violations.
   b. Run all `*.py` files in that subdirectory using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.
   e. Make only minimal, behavior-preserving edits where needed for style compliance.
   f. Update `cookbook/03_teams/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file.

4. After all agents complete, collect and merge results.

Special cases:
- `human_in_the_loop/` examples require interactive input — validate startup and initial tool call, then terminate.
- Some subdirectories require pgvector (`knowledge/`, `session/`, `distributed_rag/`, `memory/`).
- `hooks/` examples may produce output only via hook callbacks — validate execution completes without error.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/03_teams/<SUBDIR>` (for each subdirectory)
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `01_quickstart` | `01_basic_coordination.py` | PASS | Team coordinated response from both members |
| `guardrails` | `pii_detection.py` | FAIL | Missing presidio dependency |
