# Remote Cookbook

Examples for remote execution in AgentOS.

Remote execution is opt-in: an AgentOS exposes entities for remote execution by
mounting the `RemoteAccess` interface (`agno.os.interfaces.remote_access.RemoteAccess`)
and passing the agents and teams it wants to expose. `RemoteAgent` and `RemoteTeam`
are client-side proxies that call the `/remote/...` endpoints of that interface.
Entities not passed to the interface are not remotely callable.

Workflows are not remotely executable. Run workflows on their own AgentOS through the
standard workflow API (`POST /workflows/{id}/runs`) instead.

## Files

- `server.py` — Backing AgentOS server (port 7778). Mounts the RemoteAccess interface for the assistant, researcher, and team; the internal agent is deliberately not exposed.
- `01_remote_agent.py` — AgentOS app (port 7777) serving RemoteAgent proxies to the server's agents.
- `02_remote_team.py` — AgentOS app serving a RemoteTeam proxy to the server's research team.
- `03_remote_agent_as_team_member.py` — AgentOS app serving a local Team with RemoteAgent members.
- `04_agent_os_gateway.py` — Gateway AgentOS combining remote agents, a remote team, and local agents/workflows on one API.

## Running

1. Start the backing server first:
   ```
   .venvs/demo/bin/python cookbook/05_agent_os/remote/server.py
   ```
2. In a second terminal, start any of the example apps (all serve on port 7777):
   ```
   .venvs/demo/bin/python cookbook/05_agent_os/remote/01_remote_agent.py
   ```
3. Talk to the entities through the client app's API, for example:
   ```
   curl -X POST -F "message=What is 15 * 23?" -F "stream=false" http://localhost:7777/agents/assistant-agent/runs
   ```

To see the opt-in behavior, compare these against the backing server:

```
curl http://localhost:7778/remote/agents          # exposed agents only
curl http://localhost:7778/agents                 # all agents, including internal-agent
curl http://localhost:7778/remote/agents/internal-agent   # 404 - not exposed
```

## Prerequisites

- Set your `OPENAI_API_KEY` environment variable.
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.

## Notes

- RemoteAgent and RemoteTeam are async-only and talk exclusively to the `/remote/...` endpoints.
- Session, memory, and knowledge proxies (`RemoteDb`, `RemoteKnowledge`) still use the remote server's main API.
- Passing workflows to `RemoteAccess` logs an error and ignores them.
- If the backing server is unreachable, the client OS still boots and serves: each remote entity is logged as unreachable and listed with a placeholder description, and it recovers automatically once the server is back.
- Exception to auto-recovery: remote databases are discovered once, at startup. If the backing server was down when the client booted, db-scoped routes return 404 (`No database found with id '...'`) even after it comes back — call `agent_os.resync(app)` or restart the client with the server reachable. Start `server.py` first to avoid this.
