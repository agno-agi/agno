Goal: Thoroughly test and validate `cookbook/91_tools` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for knowledge_tool and database tool examples)

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Test root-level tool files and each subdirectory in parallel. Spawn agents for: root tools (batch alphabetically), `exceptions/`, `mcp/`, `models/`, `other/`, `tool_decorator/`, `tool_hooks/`.

3. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/<SUBDIR> --recursive` and fix any violations. For root tools, use `--base-dir cookbook/91_tools`.
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
- Root directory has **118+ tool files** — each demonstrates a different tool integration. Many require specific API keys or services.
- Skip tools whose dependencies or API keys are unavailable — mark as SKIP.
- `mcp/` subdirectories contain server/client pairs — validate the server starts, then terminate.
- `mcp/mcp_toolbox_demo/` is a complete demo application with Docker dependencies — validate startup only.
- `mcp/sse_transport/` and `mcp/streamable_http_transport/` contain server/client pairs — test servers separately.
- `tool_hooks/` and `tool_decorator/` contain sync/async pairs — test both variants.
- `exceptions/` examples intentionally trigger exceptions — validate the exception is raised correctly.
- Tools that require external services (Slack, Discord, GitHub, Jira, etc.) should be tested for import and setup only if API keys are missing.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools`
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/mcp --recursive`
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/tool_hooks`
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/91_tools/tool_decorator`
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| root | `calculator_tools.py` | PASS | Calculator operations completed |
| root | `slack_tools.py` | SKIP | Slack API key not available |
| `mcp` | `filesystem.py` | PASS | MCP filesystem server started |
