# Human-in-the-Loop with AgentOS

AgentOS equivalents of `cookbook/03_teams/20_human_in_the_loop/`.

Since AgentOS handles streaming and async automatically via FastAPI, each
pattern only needs a single server file (the client decides whether to use
streaming or not).

## Prerequisites

- Load environment variables (for example, `OPENAI_API_KEY`) via `direnv allow`.
- Use `.venvs/demo/bin/python` to run cookbook examples.

## Files

| AgentOS file | Original team cookbook file(s) |
|---|---|
| `confirmation_required.py` | `confirmation_required.py`, `confirmation_required_stream.py`, `confirmation_required_async.py`, `confirmation_required_async_stream.py` |
| `confirmation_rejected.py` | `confirmation_rejected.py`, `confirmation_rejected_stream.py` |
| `user_input_required.py` | `user_input_required.py`, `user_input_required_stream.py` |
| `external_tool_execution.py` | `external_tool_execution.py`, `external_tool_execution_stream.py` |
| `team_tool_confirmation.py` | `team_tool_confirmation.py`, `team_tool_confirmation_stream.py` |

## Running

```bash
# Pick any of the examples
.venvs/demo/bin/python cookbook/05_agent_os/hitl/confirmation_required.py
.venvs/demo/bin/python cookbook/05_agent_os/hitl/confirmation_rejected.py
.venvs/demo/bin/python cookbook/05_agent_os/hitl/user_input_required.py
.venvs/demo/bin/python cookbook/05_agent_os/hitl/external_tool_execution.py
.venvs/demo/bin/python cookbook/05_agent_os/hitl/team_tool_confirmation.py
```

All servers start on port `7776`. View the configuration at `http://localhost:7776/config`.

## HITL Patterns

| Pattern | Tool decorator | What happens |
|---|---|---|
| Confirmation required | `@tool(requires_confirmation=True)` | Run pauses until the client confirms |
| Confirmation rejected | `@tool(requires_confirmation=True)` | Client rejects; model acknowledges the rejection |
| User input required | `@tool(requires_user_input=True, user_input_fields=[...])` | Run pauses until the client provides the requested fields |
| External execution | `@tool(external_execution=True)` | Run pauses until the client provides the tool result |
| Team-level tool | `@tool(requires_confirmation=True)` on the team | Same as confirmation but the tool is on the team, not a member |
