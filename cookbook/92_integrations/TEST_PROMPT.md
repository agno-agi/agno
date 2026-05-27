Goal: Thoroughly test and validate `cookbook/92_integrations` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for some memory and observability examples)

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Spawn a parallel agent for each subdirectory under `cookbook/92_integrations/` (`a2a/`, `discord/`, `memory/`, `observability/`, `rag/`, `surrealdb/`). Each agent handles one subdirectory independently, including any nested subdirectories.

3. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/92_integrations/<SUBDIR> --recursive` and fix any violations.
   b. Run all `*.py` files using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.
   e. Make only minimal, behavior-preserving edits where needed for style compliance.
   f. Update TEST_LOG.md in each directory with fresh PASS/FAIL entries per file.

4. After all agents complete, collect and merge results.

Special cases:
- `a2a/basic_agent/` contains server/client components — validate the server starts, then terminate.
- `discord/` examples require a Discord bot token — skip if not available.
- `memory/` examples require specific memory service credentials (Mem0, Memori, Zep) — skip if unavailable.
- `observability/` examples require tracing service credentials (Langfuse, Phoenix, LangSmith, etc.) — skip providers whose API keys are missing.
- `observability/` files contain flag emojis in comments that need removal — replace with text labels (US, EU, Local).
- `rag/` examples require optional third-party dependencies (for example `cohere`, `wikipedia`, and `ollama`) and local services depending on file setup — skip if unavailable.
- `surrealdb/` examples require a running SurrealDB instance — skip if not available.
- `observability/teams/` has a sync/async pair to be merged — handle per RESTRUCTURE_PLAN.md.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/92_integrations/<SUBDIR> --recursive` (for each subdirectory)
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `observability` | `langfuse_via_openinference.py` | PASS | Traces exported to Langfuse |
| `discord` | `basic.py` | SKIP | Discord bot token not available |
