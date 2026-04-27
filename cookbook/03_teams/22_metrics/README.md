# metrics

Examples for team-level metrics: run metrics, streaming metrics, session metrics, and tool call timing.

## Files
- `01_team_metrics.py` - Team, session, and member-level execution metrics.
- `02_team_streaming_metrics.py` - Capturing metrics from team streaming responses with per-model detail breakdown.
- `03_team_session_metrics.py` - Session-level metrics that accumulate across multiple team runs.
- `04_team_tool_metrics.py` - Tool execution timing and member-level metrics.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require PostgreSQL (`./cookbook/scripts/run_pgvector.sh`).

## Run
- `.venvs/demo/bin/python cookbook/03_teams/metrics/<file>.py`
