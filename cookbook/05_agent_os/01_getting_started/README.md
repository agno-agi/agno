# 01 Getting Started

This lesson shows what serving an AgentOS actually creates. It mounts an agent,
team, workflow, and local knowledge base together, then uses raw HTTP to
discover the OS, run an agent with and without SSE streaming, and list the
persisted session.

## Files

| File | Description |
|---|---|
| `full_os.py` | Serves one agent, team, workflow, and Chroma-backed knowledge base on port 7777. |
| `run_over_http.py` | Calls `/config`, performs non-streaming and SSE agent runs, and lists the resulting session. |

## Endpoint map

| Primitive | Routes introduced |
|---|---|
| Agent | `GET /agents`, `POST /agents/getting-started-agent/runs` |
| Team | `GET /teams`, `POST /teams/getting-started-team/runs` |
| Workflow | `GET /workflows`, `POST /workflows/getting-started-workflow/runs` |
| Knowledge | `/knowledge/content`, `/knowledge/search`, `/knowledge/config` |
| Persistence | `GET /sessions` |
| Discovery | `GET /config` |

Agent run inputs are form fields, not a JSON body. Session lists are paginated
as `{ "data": [...], "meta": {...} }`.

## Prerequisites

Set `OPENAI_API_KEY`. SQLite and Chroma run locally and require no external
service.

## Run

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/01_getting_started/full_os.py
```

In another terminal, run the HTTP walkthrough:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/01_getting_started/run_over_http.py
```

You can also inspect the full discovery document directly:

```bash
curl http://localhost:7777/config
```
