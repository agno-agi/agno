# Python client

Use `AgentOSClient` to discover and call a running AgentOS from Python. This
lesson covers configuration, agent runs, typed streaming events, sessions,
memory, knowledge, evaluations, and central Bearer authentication.

## Files

| File | Concept |
|---|---|
| `_server.py` | Shared AgentOS server with an agent, team, workflow, and knowledge base |
| `01_connect.py` | Synchronous and asynchronous configuration discovery |
| `02_run_and_stream.py` | Non-streaming runs, typed SSE events, and cancellation |
| `03_sessions_and_memory.py` | Session lifecycle and memory CRUD |
| `04_knowledge.py` | Upload, status polling, list, search, and delete |
| `05_evals.py` | Accuracy and reliability evaluations |
| `06_auth.py` | `OS_SECURITY_KEY` Bearer authentication |

## Prerequisites

- Use `.venvs/demo/bin/python` from the repository root.
- Set `OPENAI_API_KEY` for model, embedding, and evaluation calls.
- No external database is required. The server uses SQLite and local Chroma
  storage under `tmp/`.

## Start the server

```bash
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/_server.py
```

The server owns port `7778`. Its component IDs are stable:

- Agent: `assistant`
- Team: `research-team`
- Workflow: `qa-workflow`

In another terminal, run any client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/01_connect.py
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/02_run_and_stream.py
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/03_sessions_and_memory.py
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/04_knowledge.py
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/05_evals.py
```

`AgentOSClient` provides synchronous discovery through `get_config`; the
run, session, memory, knowledge, and evaluation methods are asynchronous.
Agent, team, and workflow run methods share the same call shape.

## Enable central Bearer auth

Set the same key for the server and authenticated client:

```bash
export OS_SECURITY_KEY="replace-with-a-secret"
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/_server.py
```

Then, from another terminal:

```bash
export OS_SECURITY_KEY="replace-with-a-secret"
.venvs/demo/bin/python cookbook/05_agent_os/03_python_client/06_auth.py
```

The client constructor does not store default headers. Pass
`headers={"Authorization": f"Bearer {security_key}"}` to each operation.
For JWT, RBAC, and `agno_pat_` service accounts, continue to lesson
`07_security` in Phase 2.

## Where run lifecycle continues

The SDK does not yet expose background-run polling, checkpoint listing, or SSE
stream resumption. Those raw HTTP patterns are taught in
[`04_run_lifecycle`](../04_run_lifecycle/).
