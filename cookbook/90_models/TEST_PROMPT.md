Goal: Thoroughly test and validate `cookbook/90_models` so it aligns with our cookbook standards.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`

Execution requirements:
1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Spawn a parallel agent for each provider directory under `cookbook/90_models/`. Each agent handles one provider directory independently, including any subdirectories (e.g., `openai/chat/`, `openai/responses/`).

3. Each agent must:
   a. Run `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/90_models/<PROVIDER> --recursive` and fix any violations.
   b. Run all `*.py` files in that provider directory using `.venvs/demo/bin/python` and capture outcomes. Skip `__init__.py`.
   c. Ensure Python examples align with `cookbook/STYLE_GUIDE.md`:
      - Module docstring with `=====` underline
      - Section banners: `# ---------------------------------------------------------------------------`
      - Imports between docstring and first banner
      - `if __name__ == "__main__":` gate
      - No emoji characters
   d. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.
   e. Make only minimal, behavior-preserving edits where needed for style compliance.
   f. Update `cookbook/90_models/<PROVIDER>/TEST_LOG.md` with fresh PASS/FAIL entries per file.

4. After all agents complete, collect and merge results.

Special cases:
- This is the **largest cookbook section** with 44+ provider directories. Each provider requires its own API key.
- Skip providers whose API keys are not available — mark as SKIP with a note.
- Providers with sub-APIs use different model classes: `openai/chat/` (OpenAIChat) vs `openai/responses/` (OpenAIResponses), `ollama/chat/` vs `ollama/responses/`, etc. Test each subdirectory independently.
- `ollama/` examples require a local Ollama server — skip if not running.
- `lmstudio/` and `llamacpp/` require local model servers — skip if not running.
- `vllm/` requires a local vLLM server — skip if not running.
- Do NOT change model imports or model IDs — each file uses a specific provider.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/90_models/<PROVIDER> --recursive` (for each provider)
- `source .venv/bin/activate && ./scripts/format.sh` — format all code (ruff format)
- `source .venv/bin/activate && ./scripts/validate.sh` — validate all code (ruff check, mypy)

Final response format:
1. Findings (inconsistencies, failures, risks) with file references.
2. Test/validation commands run with results.
3. Any remaining gaps or manual follow-ups.
4. Results table in this format:

| Provider | File | Status | Notes |
|----------|------|--------|-------|
| `openai/chat` | `basic.py` | PASS | GPT-4o responded correctly |
| `ollama/chat` | `basic.py` | SKIP | Ollama server not running |
