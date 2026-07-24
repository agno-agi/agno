# AgentOS Cookbook

AgentOS is a FastAPI-based runtime that turns agents, teams, workflows, and
knowledge into roughly 80 REST endpoints and makes them available to the
[AgentOS control plane](https://os.agno.com). The same runtime can also expose
MCP, A2A, AG-UI, Slack, Telegram, and WhatsApp interfaces.

## Start here

Run the smallest useful AgentOS:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/basic.py
```

Then open [http://localhost:7777/config](http://localhost:7777/config).
`GET /config` is the payoff: it describes the registered agent, model,
database, domains, and enabled interfaces that clients and the control plane
can use. Open `/openapi.json` or `/docs` to inspect the complete REST route
surface.

## Files

| File | Description |
|---|---|
| `basic.py` | Serves the canonical one-agent AgentOS with SQLite persistence and the Agno documentation MCP tools. |
| `TEST_PROMPT.md` | Defines the repeatable live-testing workflow for this cookbook. |
| `TEST_LOG.md` | Records dated, observed results for the root example. |

## Learning path

| Lesson | What it teaches |
|---|---|
| [01_getting_started](./01_getting_started/) | Mount every core primitive, inspect the generated API, and run an agent over raw HTTP and SSE. |
| [02_databases](./02_databases/) | Set one default AgentOS database, choose a production backend, and manage schema migrations. |
| [03_python_client](./03_python_client/) | Use `AgentOSClient` for configuration, runs, sessions, memory, knowledge, evals, and authentication. |
| [04_run_lifecycle](./04_run_lifecycle/) | Treat runs as durable objects that can execute in the background, be cancelled, resumed, and checkpointed. |

Later phases extend this table as the remaining numbered lessons land.

## Canonical ports

| Port | Owner |
|---|---|
| 7777 | Every standalone example |
| 7778 | `03_python_client/_server.py` and other in-folder `_server.py` files |
| 7779 | Standalone `15_a2a` server examples |
| 7780 | `20_remote/servers/agentos_server.py` |
| 7781 | `20_remote/servers/a2a_server.py` |
| 7782 | `15_a2a/multi_agent/weather_agent.py` |
| 7783 | `15_a2a/multi_agent/airbnb_agent.py` |
| 8001 | `20_remote/servers/adk_server.py` |

## Phase 1 environment and runtime requirements

| Scope | Environment | Runtime |
|---|---|---|
| Root `basic.py` | `OPENAI_API_KEY` for agent runs | Internet access to `https://docs.agno.com/mcp` |
| `01_getting_started` | `OPENAI_API_KEY` | Local SQLite and Chroma; no external service |
| `02_databases/basic.py` | `OPENAI_API_KEY` for agent runs | Local SQLite |
| `02_databases/postgres.py` | `OPENAI_API_KEY`; optional `AGENTOS_USE_ASYNC_POSTGRES=true` | `./cookbook/scripts/run_pgvector.sh` |
| `02_databases/surreal.py` | `OPENAI_API_KEY`; optional `SURREALDB_*` overrides | `agno[surrealdb]` and `./cookbook/scripts/run_surrealdb.sh` |
| `03_python_client` | `OPENAI_API_KEY`; optional `OS_SECURITY_KEY` | In-folder server on port 7778 |
| `04_run_lifecycle` | `OPENAI_API_KEY` | Local SQLite |

Run cookbook files with `.venvs/demo/bin/python`. Development checks use
`.venv`.

## One agent, several interfaces

An agent does not have to belong to only one protocol. The same object can be
mounted on several interfaces without duplicating its instructions, tools, or
state:

```python
from agno.os.interfaces.a2a import A2A
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.slack import Slack

agent_os = AgentOS(
    agents=[agent],
    interfaces=[
        A2A(agents=[agent]),
        AGUI(agent=agent, prefix="/agui"),
        Slack(agent=agent),
    ],
)
```

The cookbook teaches those interfaces separately so each example has honest
credentials and a focused test surface; it deliberately does not ship one
all-credentials demo.
