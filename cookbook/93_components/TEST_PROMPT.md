Goal: Thoroughly test and validate `cookbook/93_components` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for save/load operations)

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive` and fix any violations.

3. Run all `*.py` files in the directory tree using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.

4. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
   - Module docstring with `=====` underline
   - Section banners: `# ---------------------------------------------------------------------------`
   - Imports between docstring and first banner
   - `if __name__ == "__main__":` gate
   - No emoji characters

5. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.

6. Make only minimal, behavior-preserving edits where needed for style compliance.

7. Update `cookbook/93_components/TEST_LOG.md` and `cookbook/93_components/workflows/TEST_LOG.md` with fresh PASS/FAIL entries per file.

Special cases:
- All save/load examples require a running PostgreSQL instance — ensure `./cookbook/scripts/run_pgvector.sh` is running.
- `save_*.py` files must be run before corresponding `get_*.py` files (save creates the entity, get retrieves it).
- `agent_os_registry.py` and `demo.py` demonstrate AgentOS with Registry — they require database access.
- `workflows/` files demonstrate save/load patterns for different workflow step types (conditional, custom, loop, parallel, router) — each uses Registry for non-serializable components.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive`
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| root | `save_agent.py` | PASS | Agent saved to database |
| root | `get_agent.py` | PASS | Agent loaded from database and responded |
| `workflows` | `save_conditional_steps.py` | PASS | Conditional workflow saved and loaded |
