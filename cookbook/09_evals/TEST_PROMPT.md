# Prompt to test: `cookbook/09_evals`

Use this prompt with an AI coding agent to test and validate the evals cookbook.

---

Goal: Thoroughly test and validate `cookbook/09_evals` so it aligns with our cookbook standards.

Context files (read these first):
- `CLAUDE.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`

Execution requirements:
1. Spawn a parallel agent for each top-level subdirectory under `cookbook/09_evals/` (`accuracy/`, `agent_as_judge/`, `performance/`, `reliability/`). Each agent handles one subdirectory independently, including any nested subdirectories within it.
2. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/09_evals/<SUBDIR> --recursive` and fix any violations.
   b. Run all `*.py` files in that subdirectory (and nested subdirectories) using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Make only minimal, behavior-preserving edits where needed for style compliance.
   e. Update `cookbook/09_evals/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file. For nested subdirectories, create a TEST_LOG.md in each.
3. After all agents complete, collect and merge results.

Special cases:
- Eval scripts may take longer to run as they perform multiple LLM calls for scoring — use a generous timeout (120s).
- `performance/` evaluations may measure latency or throughput — results will vary by environment.
- `agent_as_judge/` examples use one agent to evaluate another — expect two rounds of LLM calls.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/09_evals/<SUBDIR> --recursive` (for each subdirectory)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `accuracy/factual` | `factual_accuracy.py` | PASS | Accuracy eval completed with score |
| `performance/latency` | `latency_benchmark.py` | PASS | Latency measured within expected range |
