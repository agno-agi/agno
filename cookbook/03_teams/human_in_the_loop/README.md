# Teams Human-In-The-Loop Cookbooks

Examples for pausing and resuming team runs when a member agent needs human intervention.

## Included Examples

- `confirmation_required.py`: member tool requires explicit user approval.
- `user_input_required.py`: member tool requires additional user-provided fields.
- `external_tool_execution.py`: member tool execution happens outside the agent runtime.

## What These Show

- Member-level pauses propagating to the team run.
- Team-level `requirements` carrying member context (`member_agent_name`, `member_run_id`).
- Resuming paused runs with `team.continue_run(...)`.

## Run

```bash
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/confirmation_required.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/user_input_required.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/external_tool_execution.py
```
