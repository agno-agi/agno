Goal: Clean up and standardize `cookbook/93_components` so all Python examples pass the structure checker.

Context files (read these first):
- `AGENTS.md` — Project conventions, virtual environments, testing workflow
- `cookbook/STYLE_GUIDE.md` — Python file structure rules (canonical reference)

Environment:
- Python: `.venvs/demo/bin/python`
- API keys: loaded via `direnv allow`

Note: This directory contains component-specific examples. Do NOT migrate model classes
or model IDs — the specific model usage in each file is intentional.

Execution requirements:

1. Run the structure checker and fix all violations:
   ```
   .venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive
   ```
   Common fixes:
   - Add module docstring if missing
   - Add `if __name__ == "__main__":` gate if missing
   - Add "Create" and "Run" section banners if missing
   - Ensure "Create" section appears before "Run" section
   - Remove emoji characters
   - Ensure section banners use `# ---------------------------------------------------------------------------` style (75 dashes)

2. Ensure imports are between the module docstring and the first section banner.
   No imports should appear inside sections.

3. Make only minimal, behavior-preserving edits.
   Do not change agent logic, tool configurations, model choices, prompts, or runtime behavior.

Validation commands (must all pass before finishing):
- `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/93_components --recursive`

Final response format:
1. Summary of changes made (structural fixes).
2. Validation command output showing zero violations.
3. Files changed:

| File | Changes |
|------|---------|
| `path/to/file.py` | Added main gate, fixed banner style |
