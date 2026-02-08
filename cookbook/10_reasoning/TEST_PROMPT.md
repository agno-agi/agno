# Prompt to test: `cookbook/10_reasoning`

Use this prompt with an AI coding agent to test and validate the reasoning cookbook.

---

Goal: Thoroughly test and validate `cookbook/10_reasoning` so it aligns with our cookbook standards.

Context files (read these first):
- `CLAUDE.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`

Execution requirements:
1. Spawn a parallel agent for each top-level subdirectory under `cookbook/10_reasoning/` (`agents/`, `models/`, `teams/`, `tools/`). Each agent handles one subdirectory independently, including any nested subdirectories within it.
2. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/10_reasoning/<SUBDIR> --recursive` and fix any violations.
   b. Run all `*.py` files in that subdirectory (and nested subdirectories) using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Make only minimal, behavior-preserving edits where needed for style compliance.
   e. Update `cookbook/10_reasoning/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file. For nested subdirectories, create a TEST_LOG.md in each.
3. After all agents complete, collect and merge results.

Special cases:
- Reasoning examples may produce longer outputs with chain-of-thought — use a generous timeout (120s).
- `models/` subdirectories may require specific model provider API keys — skip if unavailable.
- `tools/` examples combine reasoning with tool use — may require additional API keys (e.g., web search).

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/10_reasoning/<SUBDIR> --recursive` (for each subdirectory)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `agents/chain_of_thought` | `cot_agent.py` | PASS | Reasoning chain produced correct result |
| `models/deepseek` | `deepseek_reasoning.py` | SKIP | DeepSeek API key not available |
