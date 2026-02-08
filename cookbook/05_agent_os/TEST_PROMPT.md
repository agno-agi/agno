# Prompt to test: `cookbook/05_agent_os`

Use this prompt with an AI coding agent to test and validate the Agent OS cookbook.

---

Goal: Thoroughly test and validate `cookbook/05_agent_os` so it aligns with our cookbook standards.

Context files (read these first):
- `CLAUDE.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for knowledge and database examples)

Execution requirements:
1. Spawn a parallel agent for each top-level subdirectory under `cookbook/05_agent_os/`. Each agent handles one subdirectory independently, including any nested subdirectories within it.
2. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/05_agent_os/<SUBDIR> --recursive` and fix any violations.
   b. Run all `*.py` files in that subdirectory using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Make only minimal, behavior-preserving edits where needed for style compliance.
   e. Update `cookbook/05_agent_os/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file.
3. After all agents complete, collect and merge results.

Special cases:
- `client_a2a/` contains server/client pairs — validate the server starts, then terminate. Do not wait for client connections.
- `mcp_demo/` contains MCP server examples — validate startup only.
- `background_tasks/` examples may spawn background tasks — validate execution starts and terminate after initial output.
- `rbac/` contains symmetric and asymmetric encryption examples — both subdirectories should be tested independently.
- Root-level files (`agno_agent.py`, `basic.py`, `demo.py`) should be tested as standalone examples.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/05_agent_os/<SUBDIR> --recursive` (for each subdirectory)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `rbac/symmetric` | `rbac_demo.py` | PASS | Symmetric RBAC enforced correctly |
| `mcp_demo` | `server.py` | PASS | MCP server started successfully |
