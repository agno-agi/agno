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
| [05_human_in_the_loop](./05_human_in_the_loop/) | Pause runs for confirmation, user input, external execution, or persistent approval records, then resume them correctly. |
| [06_customize](./06_customize/) | Extend the FastAPI app with base apps, route policies, lifespans, middleware, events, dependencies, CORS, and a security key. |
| [07_security](./07_security/) | Secure AgentOS with JWTs, RBAC scopes, cookies, user isolation, service accounts, and a bring-your-own issuer. |
| [08_os_config](./08_os_config/) | Shape the control-plane manifest in Python or YAML and inspect the rendered `/config`. |
| [09_serving_workflows](./09_serving_workflows/) | Serve workflows over REST, SSE, and the workflow-only WebSocket surface. |
| [10_knowledge](./10_knowledge/) | Serve one knowledge base and manage its content through the AgentOS REST API. |
| [11_learnings](./11_learnings/) | Persist user profiles and memories, then read and manage them through the learnings API. |
| [12_scheduler](./12_scheduler/) | Run scheduled agents through AgentOS, REST, Python, and SchedulerTools with production-safe claiming. |
| [13_observability](./13_observability/) | Capture, read, filter, and route traces, then refresh and inspect AgentOS metrics. |
| [14_mcp](./14_mcp/) | Expose AgentOS as a scoped MCP server, drive its run lifecycle, and secure it with PAT or OAuth authorization. |
| [15_a2a](./15_a2a/) | Serve agents and teams over A2A, use the first-party client, inspect agent cards, and compose remote agents. |
| [16_agui](./16_agui/) | Serve standalone AG-UI agents and teams with tools, media, shared state, structured output, and backend HITL. |
| [17_slack](./17_slack/) | Connect agents, teams, and workflows to Slack with streaming UX, workspace tools, threaded sessions, peer bots, and HITL. |
| [18_telegram](./18_telegram/) | Serve Telegram bots with streaming replies, group mention filtering, media, commands, and multiple prefixes. |
| [19_whatsapp](./19_whatsapp/) | Serve WhatsApp assistants with interactive messages, media, reasoning, webhook verification, and multiple numbers. |
| [20_remote](./20_remote/) | Compose AgentOS, Agno A2A, and Google ADK services through RemoteAgent, RemoteTeam, and RemoteWorkflow. |
| [21_factories](./21_factories/) | Construct request-scoped agents, teams, and workflows from validated input and trusted identity. |
| [22_studio](./22_studio/) | Compose, version, inspect, and approve AgentOS components with the Registry, StudioTools, and components API. |
| [23_skills](./23_skills/) | Serve local skills through an Agent and execute checked-in skill scripts through the AgentOS run API. |
| [24_showcase](./24_showcase/) | Run the secure, traced capstone with RAG, web and finance research, a Team, and a real evaluation. |

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

## Environment and runtime requirements

| Scope | Environment | Runtime |
|---|---|---|
| Root `basic.py` | `OPENAI_API_KEY` for agent runs | Internet access to `https://docs.agno.com/mcp` |
| `01_getting_started` | `OPENAI_API_KEY` | Local SQLite and Chroma; no external service |
| `02_databases/basic.py` | `OPENAI_API_KEY` for agent runs | Local SQLite |
| `02_databases/postgres.py` | `OPENAI_API_KEY`; optional `AGENTOS_USE_ASYNC_POSTGRES=true` | `./cookbook/scripts/run_pgvector.sh` |
| `02_databases/surreal.py` | `OPENAI_API_KEY`; optional `SURREALDB_*` overrides | `agno[surrealdb]` and `./cookbook/scripts/run_surrealdb.sh` |
| `03_python_client` | `OPENAI_API_KEY`; optional `OS_SECURITY_KEY` | In-folder server on port 7778 |
| `04_run_lifecycle` | `OPENAI_API_KEY` | Local SQLite |
| `05_human_in_the_loop` | `OPENAI_API_KEY` | Local SQLite for persistent approvals |
| `06_customize` | `OPENAI_API_KEY`; optional `OS_SECURITY_KEY` | Local FastAPI app on port 7777 |
| `07_security` | `OPENAI_API_KEY`; WorkOS values only for `workos_byot.py` | Local JWT keys and SQLite; WorkOS example may use construction smoke |
| `08_os_config` | `OPENAI_API_KEY` for agent runs | Python or YAML configuration on port 7777 |
| `09_serving_workflows` | `OPENAI_API_KEY` | Local workflow server on port 7777 |
| `10_knowledge` | `OPENAI_API_KEY` | Local SQLite and Chroma |
| `11_learnings` | `OPENAI_API_KEY` | Local SQLite |
| `12_scheduler` | `OPENAI_API_KEY` | `agno[scheduler]` and `./cookbook/scripts/run_pgvector.sh` |
| `13_observability` | `OPENAI_API_KEY` | Local SQLite; Postgres and ClickHouse only for the split trace-store example |
| `14_mcp` | `OPENAI_API_KEY`; `OS_SECURITY_KEY` for PAT security; provider values for AuthKit OAuth | Local SQLite and an MCP client |
| `15_a2a` | `OPENAI_API_KEY`; `OPENWEATHER_API_KEY` for the weather specialist | Standalone servers on ports 7779, 7782, and 7783; Node.js, `npx`, and internet access for OpenBNB |
| `16_agui` | `OPENAI_API_KEY`; `GOOGLE_API_KEY` for the media example | Local AG-UI servers; a CopilotKit frontend is optional for interactive UI testing |
| `17_slack` | Slack bot tokens and signing secrets; provider keys used by each served entity | Slack app configuration and a public HTTPS callback; construction smoke is valid without a live workspace |
| `18_telegram` | Telegram bot tokens; provider keys used by each served entity | `agno[telegram]` and a public HTTPS callback; construction smoke is valid without live bots |
| `19_whatsapp` | Meta access, phone-number, verify-token, and app-secret values; provider keys used by each served entity | A Meta app and public HTTPS callback; construction smoke is valid without live phone numbers |
| `20_remote` | `OPENAI_API_KEY`; `GOOGLE_API_KEY` for ADK; `OS_SECURITY_KEY` for the auth example | AgentOS on 7780, Agno A2A on 7781, Google ADK on 8001, and gateway on 7777 |
| `21_factories` | `OPENAI_API_KEY` | Local SQLite; no external service |
| `22_studio` | `OPENAI_API_KEY`; `ANTHROPIC_API_KEY` for Claude-backed runs | Local synchronous SQLite for Registry and components CRUD |
| `23_skills` | `OPENAI_API_KEY` | Local sample-skill files with executable Python scripts |
| `24_showcase` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OS_SECURITY_KEY` | `./cookbook/scripts/run_pgvector.sh`, internet access, and tracing |

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
