# session

Examples for session persistence, summaries, options, and history access.

## Files
- `chat_history.py` - Demonstrates chat history.
- `last_n_session_messages.py` - Demonstrates last n session messages.
- `persistent_session.py` - Demonstrates persistent session.
- `session_options.py` - Demonstrates session options.
- `session_summary.py` - Demonstrates session summary.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
