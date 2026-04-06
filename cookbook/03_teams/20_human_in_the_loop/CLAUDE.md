# CLAUDE.md - Team Human-in-the-Loop Cookbook

Instructions for Claude Code when testing the Team HITL cookbooks.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/confirmation_required.py
.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/external_tool_execution.py
.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/user_input_required.py
```

**Test results file:**
```
cookbook/03_teams/20_human_in_the_loop/TEST_LOG.md
```

---

## Testing Workflow

### 1. Before Testing

- Ensure the virtual environment exists (run `./scripts/demo_setup.sh` if needed)
- Set `OPENAI_API_KEY` environment variable

### 2. Running Tests

Each script is interactive and requires terminal input:
- **confirmation_required.py** -- Prompts y/n to approve/deny a weather lookup
- **external_tool_execution.py** -- Prompts for the result of an external email send
- **user_input_required.py** -- Prompts for destination and budget values

### 3. Expected Behavior

All three examples follow the same pattern:
1. Team delegates task to a member agent
2. Member encounters a HITL tool and pauses
3. Pause propagates to the team level with member context
4. User resolves the requirement (confirm/reject, provide input, or provide result)
5. `team.continue_run()` routes the resolution back to the member and completes

### 4. Known Issues

- These examples use SQLite (`tmp/team_hitl.db`) for session persistence
- The `tmp/` directory must be writable (created automatically)

---

## Code Locations

| What | Where |
|------|-------|
| RunRequirement | `libs/agno/agno/run/requirement.py` |
| Team HITL pause handlers | `libs/agno/agno/team/_hooks.py` |
| Team continue_run dispatch | `libs/agno/agno/team/_run.py` |
| Member pause propagation | `libs/agno/agno/team/_tools.py` |
| Integration tests | `libs/agno/tests/integration/teams/human_in_the_loop/` |
