Goal: Clean up and standardize `cookbook/00_quickstart` so all Python examples pass the structure checker and use current model conventions.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules (canonical reference)

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`

Execution requirements:

1. **Read every `.py` file** in the target cookbook directory before making any changes.
   Do not rely solely on grep or the structure checker — open and read each file to understand its full contents. This ensures you catch issues the automated checker might miss (e.g., imports inside sections, stale model references in comments, inconsistent patterns).

2. Run the structure checker and fix all violations:
   ```
   .venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart --recursive
   ```
   Common fixes:
   - Add module docstring if missing
   - Add `if __name__ == "__main__":` gate if missing
   - Add "Create" and "Run" section banners if missing
   - Ensure "Create" section appears before "Run" section
   - Remove emoji characters
   - Ensure section banners use `# ---------------------------------------------------------------------------` style (75 dashes)

3. Ensure imports are between the module docstring and the first section banner.
   No imports should appear inside sections.

4. Migrate OpenAI model references. Only change files that use OpenAI models.
   Do NOT modify files using other providers (Gemini, Claude, Groq, Ollama, etc.).

   | Before | After |
   |--------|-------|
   | `from agno.models.openai import OpenAIChat` | `from agno.models.openai import OpenAIResponses` |
   | `OpenAIChat(id="gpt-4o")` | `OpenAIResponses(id="gpt-5.2")` |
   | `OpenAIChat(id="gpt-4o-mini")` | `OpenAIResponses(id="gpt-5.2-mini")` |
   | Any other `OpenAIChat(` usage | `OpenAIResponses(` with updated model ID |

   If a file imports both `OpenAIChat` and another provider, only change the OpenAI parts.

5. Also check non-Python files (`README.md`, etc.) in the directory for stale `OpenAIChat` references and update them.

6. Make only minimal, behavior-preserving edits.
   Do not change agent logic, tool configurations, prompts, or runtime behavior.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/00_quickstart --recursive`

Final response format:
1. Summary of changes made (structural fixes, model migrations).
2. Validation command output showing zero violations.
3. Files changed:

| File | Changes |
|------|---------|
| `path/to/file.py` | OpenAIChat -> OpenAIResponses, added main gate |
