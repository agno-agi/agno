# Review Log — remote/

## Framework Issues

[FRAMEWORK] agno/client/os.py — `RemoteAgent`, `RemoteTeam`, and `RemoteWorkflow` constructors eagerly connect to the remote server at init time (fetching config). This prevents constructing a gateway AgentOS that aggregates remote sources without all backends already running. A lazy-connect pattern would be more resilient.

## Cookbook Quality

[QUALITY] 03_remote_agno_a2a_agent.py:9 — Docstring references `cookbook/06_agent_os/remote/agno_a2a_server.py` (old path). Should be `cookbook/05_agent_os/remote/agno_a2a_server.py`.

[QUALITY] 04_remote_adk_agent.py:9 — Docstring references `cookbook/06_agent_os/remote/adk_server.py` (old path). Should be `cookbook/05_agent_os/remote/adk_server.py`.

## Fixes Applied

(none)
