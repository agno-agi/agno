Goal: Thoroughly test and validate `cookbook/02_agents` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`
- Database: `./cookbook/scripts/run_pgvector.sh` (needed for RAG, session, knowledge examples)

Execution requirements:
1. Spawn a parallel agent for each subdirectory under `cookbook/02_agents/`. Each agent handles one subdirectory independently.
2. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/02_agents/<SUBDIR>` and fix any violations.
   b. Run all `*.py` files in that subdirectory using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Make only minimal, behavior-preserving edits where needed for style compliance.
   e. Update `cookbook/02_agents/<SUBDIR>/TEST_LOG.md` with fresh PASS/FAIL entries per file.
3. After all agents complete, collect and merge results.

Special cases:
- `human_in_the_loop/` examples require interactive input — validate startup and initial tool call, then terminate.
- Some subdirectories require pgvector (`rag/`, `session/`, `culture/`).
- Multimodal examples may require specific API keys (OpenAI for audio, FAL for image generation).

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/02_agents/<SUBDIR>` (for each subdirectory)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Subdirectory | File | Status | Notes |
|-------------|------|--------|-------|
| `caching` | `cache_model_response.py` | PASS | Cached response returned on second call |
| `guardrails` | `pii_detection.py` | FAIL | Missing presidio dependency |
