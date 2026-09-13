# human in the loop

Examples for team workflows in human_in_the_loop.

## Prerequisites

- Load `OPENAI_API_KEY` (for example, with `direnv allow`).
- Use `.venvs/demo/bin/python` to run cookbook examples.
- Most examples persist paused runs to SQLite files under `tmp/`.
  `team_tool_confirmation_stream.py` uses PostgreSQL instead. Start the local
  database with `./cookbook/scripts/run_pgvector.sh` before running it.
- `confirmation_required_async.py`, `confirmation_rejected.py`,
  `confirmation_required_with_dependencies.py`, and `team_tool_confirmation.py`
  configure no database. They pause and resume within a single process, so the
  paused run is not recoverable after the script exits.

## Files

- `confirmation_required.py` - Confirm or reject a member tool call.
- `confirmation_required_async.py` - Confirm a member tool call asynchronously.
- `confirmation_required_stream.py` - Confirm a member tool call while streaming.
- `confirmation_required_async_stream.py` - Confirm a member tool call with async streaming.
- `confirmation_required_with_dependencies.py` - Preserve caller dependencies when an async member run resumes.
- `confirmation_rejected.py` - Reject a member tool call and continue the team run.
- `confirmation_rejected_stream.py` - Reject a member tool call while streaming.
- `user_input_required.py` - Collect required user input for a member tool.
- `user_input_required_stream.py` - Provide required user input while streaming.
- `multi_round_user_input.py` - Handle multiple member pause and resume cycles.
- `external_tool_execution.py` - Return an externally produced result to a member tool.
- `external_tool_execution_stream.py` - Execute a member tool externally while streaming.
- `team_tool_confirmation.py` - Confirm a tool attached directly to the Team.
- `team_tool_confirmation_stream.py` - Confirm a Team-level tool while streaming with PostgreSQL persistence.
