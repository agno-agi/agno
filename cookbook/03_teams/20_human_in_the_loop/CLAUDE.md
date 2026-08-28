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
.venvs/demo/bin/python cookbook/03_teams/20_human_in_the_loop/<example>.py
```

| Pattern | Examples |
|---------|----------|
| Member confirmation | `confirmation_required.py`, `confirmation_required_async.py`, `confirmation_required_stream.py`, `confirmation_required_async_stream.py` |
| Dependency forwarding | `confirmation_required_with_dependencies.py` |
| Member rejection | `confirmation_rejected.py`, `confirmation_rejected_stream.py` |
| User input | `user_input_required.py`, `user_input_required_stream.py`, `multi_round_user_input.py` |
| External execution | `external_tool_execution.py`, `external_tool_execution_stream.py` |
| Team-level tool confirmation | `team_tool_confirmation.py`, `team_tool_confirmation_stream.py` |

**Test results file:**
```
cookbook/03_teams/20_human_in_the_loop/TEST_LOG.md
```

---

## Testing Workflow

### 1. Before Testing

- Ensure the virtual environment exists (run `./scripts/demo_setup.sh` if needed)
- Set `OPENAI_API_KEY` environment variable
- Start PostgreSQL with `./cookbook/scripts/run_pgvector.sh` before running
  `team_tool_confirmation_stream.py`

### 2. Running Tests

These scripts require terminal input:
- **confirmation_required.py** -- Prompts y/n to approve/deny a weather lookup
- **external_tool_execution.py** -- Prompts for the result of an external email send
- **user_input_required.py** -- Prompts for destination and budget values
- **multi_round_user_input.py** -- Prompts for name, then cuisine/budget (2 HITL rounds)

The other examples resolve their requirements programmatically after the model
pauses, so they require no terminal input.

### 3. Expected Behavior

Member-tool examples follow this pattern:
1. Team delegates task to a member agent
2. Member encounters a HITL tool and pauses
3. Pause propagates to the team level with member context
4. User resolves the requirement (confirm/reject, provide input, or provide result)
5. `team.continue_run()` or `team.acontinue_run()` routes the resolution back to the member and completes

Team-level tool examples pause when the Team calls its own guarded tool. The
caller resolves that requirement and resumes the Team directly with
`team.continue_run()`.

### 4. Persistence Prerequisites

- Most persisted examples use SQLite under `tmp/`
- `team_tool_confirmation_stream.py` uses PostgreSQL at
  `postgresql+psycopg://ai:ai@localhost:5532/ai`
- `confirmation_required_async.py`, `confirmation_rejected.py`,
  `confirmation_required_with_dependencies.py`, and `team_tool_confirmation.py`
  configure no `db`, so they need no database setup and write no session rows
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
