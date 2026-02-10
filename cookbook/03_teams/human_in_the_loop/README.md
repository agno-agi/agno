# Human-in-the-Loop (HITL) for Teams

Human-in-the-Loop enables teams to pause execution when a tool requires human intervention before proceeding. This covers four scenarios:

1. **Confirmation Required** - A tool needs explicit human approval before executing (e.g., deploying to production)
2. **Confirmation Rejected** - The human rejects a tool call and the team handles the rejection gracefully
3. **User Input Required** - A tool needs additional information from the user before it can run
4. **External Tool Execution** - A tool is executed outside the agent and the result is provided back
5. **Team-Level Tool HITL** - Tools provided directly to the team (not member agents) can also require confirmation

## Examples

| File | Description |
|------|-------------|
| `confirmation_required.py` | Member agent tool requiring confirmation (sync) |
| `confirmation_required_async.py` | Member agent tool requiring confirmation (async) |
| `confirmation_rejected.py` | Member agent tool call rejected with a note |
| `user_input_required.py` | Member agent tool requiring user input |
| `external_tool_execution.py` | Member agent tool executed externally |
| `team_tool_confirmation.py` | Team-level tool requiring confirmation |

## Running

```bash
# Requires OPENAI_API_KEY
export OPENAI_API_KEY=your-key

# Run individual examples
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/confirmation_required.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/confirmation_required_async.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/confirmation_rejected.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/user_input_required.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/external_tool_execution.py
.venvs/demo/bin/python cookbook/03_teams/human_in_the_loop/team_tool_confirmation.py
```

## How It Works

1. A team `run()` returns a `TeamRunOutput` with `is_paused=True` when HITL is needed
2. The `requirements` list on the response contains `RunRequirement` objects describing what is needed
3. Call `.confirm()`, `.reject()`, `.provide_user_input()`, or `.set_external_execution_result()` on each requirement
4. Call `team.continue_run(response)` to resume execution
