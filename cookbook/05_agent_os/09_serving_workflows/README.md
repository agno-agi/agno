# Serving workflows

Workflow authoring belongs in [`cookbook/04_workflows`](../../04_workflows/).
This lesson starts where authoring ends: it shows what AgentOS adds when a
Workflow becomes a served resource.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Serve a canonical two-step, database-backed Workflow. |
| `with_workflow_agent.py` | Chat with a WorkflowAgent over HTTP and reuse workflow history. |
| `with_input_schema.py` | Expose a Pydantic `input_schema` in workflow detail for structured clients. |
| `run_over_api.py` | Create a run, consume SSE events, and list persisted runs with raw `httpx`. |
| `ws_stream.py` | Stream workflow events through the genuine `/workflows/ws` WebSocket. |

## Prerequisites

Set `OPENAI_API_KEY` for the live Workflow, WebSocket, and WorkflowAgent
clients. Inspecting the served input schema does not call a model and needs no
external credentials.

## What serving adds

Running `basic.py` registers `release-notes-workflow` and exposes:

- `GET /config` and `GET /workflows` for discovery;
- `GET /workflows/{workflow_id}` for detailed workflow configuration;
- `POST /workflows/{workflow_id}/runs` for non-streaming or SSE execution;
- `GET /workflows/{workflow_id}/runs?session_id=...` for persisted run history;
- `GET /workflows/{workflow_id}/runs/{run_id}?session_id=...` for one run;
- `/workflows/ws` for bidirectional WebSocket execution and reconnection.

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/basic.py
```

Then exercise both network clients:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/run_over_api.py
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/ws_stream.py
```

`run_over_api.py` posts form fields because the AgentOS run route accepts
`message`, `stream`, and `session_id` as form data. It performs one complete
JSON run, one SSE run, and verifies that both IDs appear in the session's run
listing.

`ws_stream.py` uses the WebSocket protocol rather than an HTTP stream with a
misleading name. It connects to `/workflows/ws`, sends the
`start-workflow` action, and consumes indexed events through
`WorkflowCompleted`. Agent and Team run routes stream with SSE; this WebSocket
surface is workflow-only.

## WorkflowAgent

Start the WorkflowAgent server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/with_workflow_agent.py
```

Then send a new topic and a history-aware follow-up:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/with_workflow_agent.py --demo
```

The WorkflowAgent may invoke the workflow for new work or answer directly from
the persisted workflow history. `GET /workflows/{id}` reports
`workflow_agent: true`, so clients can identify the served behavior.

## Input schema

Start the input-schema server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/with_input_schema.py
```

Then inspect its served schema:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/09_serving_workflows/with_input_schema.py --demo
```

AgentOS serializes the Workflow's Pydantic model as `input_schema` in
`GET /workflows/{id}`. The control-plane chat client uses that schema to render
structured fields instead of one free-form message box.
