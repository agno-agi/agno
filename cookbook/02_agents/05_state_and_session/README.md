# 05_state_and_session

Examples for session state management, chat history, and session persistence.

## Files
- `agentic_session_state.py` - Agent-managed session state updates.
- `chat_history.py` - Access and manage chat history.
- `dynamic_session_state.py` - Dynamic session state with computed values.
- `last_n_session_messages.py` - Limit context to the last N messages.
- `persistent_session.py` - Persist sessions across restarts with a database.
- `session_options.py` - Configure session options.
- `session_state_advanced.py` - Advanced session state patterns.
- `session_state_basic.py` - Basic session state usage.
- `session_state_events.py` - Session state change events.
- `session_state_manual_update.py` - Manually update session state.
- `session_state_multiple_users.py` - Session state with multiple users.
- `session_summary.py` - Enable session summaries for context compression.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require PostgreSQL: `./cookbook/scripts/run_pgvector.sh`

## Run
- `.venvs/demo/bin/python cookbook/02_agents/05_state_and_session/<file>.py`
