# Prompt to test: `cookbook/04_workflows`

Use this prompt with an AI coding agent to test and validate the workflows cookbook.

---

Goal: Thoroughly test and validate `cookbook/04_workflows` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for session state and history examples)

Execution requirements:
1. Spawn a parallel agent for each top-level subdirectory under `cookbook/04_workflows/`. Each agent handles one subdirectory independently, including any nested subdirectories within it.
2. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/04_workflows/<SUBDIR>` and fix any violations. For `06_advanced_concepts/`, run the checker on each nested subdirectory separately.
   b. Run all `*.py` files in that subdirectory (and nested subdirectories) using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Make only minimal, behavior-preserving edits where needed for style compliance.
   e. Update `cookbook/04_workflows/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file. For `06_advanced_concepts/`, create a TEST_LOG.md in each nested subdirectory.
3. After all agents complete, collect and merge results.

Special cases:
- `06_advanced_concepts/background_execution/` contains WebSocket server/client pairs — validate the server starts, then terminate. Do not wait for WebSocket connections.
- `06_advanced_concepts/long_running/` examples require a running WebSocket server — validate startup only, then terminate.
- `06_advanced_concepts/workflow_agent/` uses WorkflowAgent which may require longer execution times — use a generous timeout (120s).
- `07_cel_expressions/` files use CEL (Common Expression Language) — these require the `celpy` package.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/04_workflows/<SUBDIR>` (for each subdirectory)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `01_basic_workflows/01_sequence_of_steps` | `sequence_of_steps.py` | PASS | Sequential workflow completed both steps |
| `07_cel_expressions/condition` | `cel_basic.py` | FAIL | Missing celpy dependency |
