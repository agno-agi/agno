# CLAUDE.md - Team Human-in-the-Loop Cookbook

Instructions for testing the Team HITL cookbooks.

---

## Quick Reference

**Test Environment:**
```bash
# Virtual environment with all dependencies
.venvs/demo/bin/python

# Required environment variable
export OPENAI_API_KEY=your-key
```

**Run a cookbook:**
```bash
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/confirmation_required.py
```

---

## Cookbook Files

| File | What It Tests |
|------|---------------|
| `confirmation_required.py` | Member agent tool pause + confirm + continue_run |
| `confirmation_required_async.py` | Async variant of confirmation flow |
| `confirmation_rejected.py` | Member agent tool pause + reject with note + continue_run |
| `user_input_required.py` | Member agent tool pause + provide_user_input + continue_run |
| `external_tool_execution.py` | Member agent tool pause + set_external_execution_result + continue_run |
| `team_tool_confirmation.py` | Team-level tool pause + confirm + continue_run |

---

## Expected Behavior

Each cookbook should:
1. Print that the team is paused
2. Show the tool name and arguments (or fields needed)
3. Print the final result after continue_run completes

If the model does not invoke the HITL tool, the response will print directly without pausing. This depends on model behavior.

---

## No Database Required

These examples do not require a database. They use in-memory sessions only.
