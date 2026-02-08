# Prompt to test: `cookbook/01_demo`

Use this prompt with an AI coding agent to test and validate the demo cookbook.

---

Goal: Thoroughly test and validate `cookbook/01_demo` so it aligns with our cookbook standards.

Context files (read these first):
- `CLAUDE.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for database-backed agents)

Execution requirements:
1. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/01_demo --recursive` and fix any violations.
2. Run all `*.py` files in the directory tree using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
3. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
   - Module docstring with `=====` underline
   - Section banners: `# ---------------------------------------------------------------------------`
   - Imports between docstring and first banner
   - `if __name__ == "__main__":` gate
   - No emoji characters
4. Make only minimal, behavior-preserving edits where needed for style compliance.
5. Update `cookbook/01_demo/TEST_LOG.md` with fresh PASS/FAIL entries per file.

Special cases:
- `run.py` is a long-running server — validate startup only, then terminate.
- `db.py` and `registry.py` are support modules, not standalone examples — validate they import without error.
- Agent, team, and workflow subdirectories contain runnable demos that may depend on `config.yaml` and registry setup.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/01_demo --recursive`

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| File | Status | Notes |
|------|--------|-------|
| `run.py` | PASS | Server started successfully |
| `db.py` | PASS | Module imports without error |
