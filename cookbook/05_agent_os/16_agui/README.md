# AG-UI

AG-UI is an event-stream protocol between an agent backend and an interactive
frontend. AgentOS translates Agent and Team run events into AG-UI text, tool,
reasoning, state, and lifecycle events, while keeping the model, tools,
sessions, and approval state on the server.

Every example in this folder is a standalone server. A client sends a
`RunAgentInput` to `POST {prefix}/agui` and receives
`text/event-stream`. The same interface exposes `GET {prefix}/status`; with the
default empty prefix those routes are `POST /agui` and `GET /status`.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Mount one agent at the default `/agui` and `/status` routes. |
| `agent_with_tools.py` | Contrast a Python backend tool with a frontend-supplied external-execution tool. |
| `structured_output.py` | Stream a response constrained by a Pydantic output schema. |
| `reasoning_agent.py` | Translate Agno reasoning lifecycle events into AG-UI reasoning events. |
| `agent_with_media.py` | Pass AG-UI image, audio, video, and document parts to Gemini. |
| `shared_state.py` | Send state snapshots and JSON Patch deltas as session state changes. |
| `human_in_the_loop.py` | Pause and resume a real backend tool that uses `requires_confirmation`. |
| `research_team.py` | Stream a coordinated Team and its member activity over AG-UI. |
| `multiple_instances.py` | Mount two independent AG-UI interfaces on one AgentOS. |
| `background_runs.py` | Run detached with `forwarded_props: {"background": true}` and reattach after disconnect with `{"reattach": true}`. |
| `openui/` | Render an Agent as streaming charts, follow-ups, and validated forms with OpenUI. |

## Prerequisites

Install the demo environment, then export the provider key used by the file:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...  # agent_with_media.py only
```

`research_team.py` also needs internet access for `WebSearchTools`.

## Run

Start one example at a time; every standalone server uses port 7777:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/basic.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_tools.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/structured_output.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/reasoning_agent.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_media.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/shared_state.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/human_in_the_loop.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/research_team.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/multiple_instances.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/background_runs.py
```

The [`openui/`](openui/) example includes its own React client. Follow its
README to generate the OpenUI component prompt, run `openui/server.py`, and
start the frontend.

Point an AG-UI client such as CopilotKit or the AG-UI Dojo at the matching
endpoint:

| Running file | POST event stream | Status |
|---|---|---|
| `basic.py` | `http://localhost:7777/agui` | `http://localhost:7777/status` |
| `agent_with_tools.py` | `http://localhost:7777/tools/agui` | `http://localhost:7777/tools/status` |
| `structured_output.py` | `http://localhost:7777/structured-output/agui` | `http://localhost:7777/structured-output/status` |
| `reasoning_agent.py` | `http://localhost:7777/reasoning/agui` | `http://localhost:7777/reasoning/status` |
| `agent_with_media.py` | `http://localhost:7777/media/agui` | `http://localhost:7777/media/status` |
| `shared_state.py` | `http://localhost:7777/shared-state/agui` | `http://localhost:7777/shared-state/status` |
| `human_in_the_loop.py` | `http://localhost:7777/human-in-the-loop/agui` | `http://localhost:7777/human-in-the-loop/status` |
| `research_team.py` | `http://localhost:7777/research-team/agui` | `http://localhost:7777/research-team/status` |
| `multiple_instances.py` | `http://localhost:7777/chat/agui` and `http://localhost:7777/analyst/agui` | `/chat/status` and `/analyst/status` |
| `openui/server.py` | `http://localhost:7777/agui` | `http://localhost:7777/status` |

The old all-in-one showcase is intentionally gone: starting the file you are
learning makes its endpoint available directly, without import-only support
modules.

## The event stream

A minimal request against `basic.py` is:

```bash
curl -N http://localhost:7777/agui \
  -H 'Content-Type: application/json' \
  -d '{
    "threadId": "agui-readme-thread",
    "runId": "agui-readme-run",
    "state": {},
    "messages": [
      {"id": "message-1", "role": "user", "content": "Say hello in five words."}
    ],
    "tools": [],
    "context": [],
    "forwardedProps": {}
  }'
```

The stream begins with `RUN_STARTED`, emits message or capability-specific
events, and ends with `RUN_FINISHED`. Tool calls use `TOOL_CALL_*`; reasoning
uses `REASONING_*`; shared state uses `STATE_SNAPSHOT` and `STATE_DELTA`.
`threadId` becomes the Agno session ID, so later requests can continue the same
conversation.

## Background runs and reattach

With `forwarded_props: {"background": true}` the run executes in a detached server task: closing the SSE connection does not cancel it, and its events are buffered server-side so any client can reattach later. This powers refresh-proof chats — a user can reload the page, switch devices, or open a second tab while an answer is still generating. Background execution requires a database on the agent or team, is not available for remote entities, and mirrors the per-request opt-in of the REST run endpoints.

The recovery flow builds on the session APIs the frontend already calls. `GET /sessions/{session_id}` reports an `active_run` field (`run_id` + `status`) whenever the thread has a PENDING/RUNNING run whose event stream is still live, and `POST /agui/reattach` subscribes to that run's AG-UI events without starting a new run:

```typescript
// 1. Open the conversation — the same call that loads history also answers
//    "is this thread still generating?"
const session = await fetch(`${AGENTOS_BASE}/sessions/${threadId}?type=agent`).then(r => r.json());
renderHistory(session.chat_history);

// 2. If a run is in progress, reattach to its event stream
if (session.active_run) {
  const response = await fetch(`${AGENTOS_BASE}/agui/reattach`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, run_id: session.active_run.run_id }),
  });
  // RUN_STARTED → MESSAGES_SNAPSHOT (everything produced so far) → live deltas
  // (or RUN_FINISHED immediately if the run already ended)
  await consumeStream(response.body);
}
```

`run_id` is optional on `POST /agui/reattach`: omit it and the server resolves the thread's in-progress run itself (404 when nothing is running — the client renders history alone). An explicit but unknown `run_id` also 404s; it is never silently swapped for another run. Reattach is also available in flag form on the run endpoint (`POST /agui` with `forwarded_props: {"reattach": true}` and an empty-string `run_id` as the auto-resolve sentinel, since the AG-UI protocol requires the field) for clients built on `@ag-ui/client`'s `HttpAgent`; the dedicated route is preferred for new integrations.

Server behavior on reattach:

| Run state | Response |
|---|---|
| Active (PENDING/RUNNING) | `RUN_STARTED` → `MESSAGES_SNAPSHOT` of the missed prefix → live events |
| Finished, buffer retained (1h) | `RUN_STARTED` → `MESSAGES_SNAPSHOT` → `RUN_FINISHED` |
| Finished, buffer expired | Same, rebuilt from the stored run in the database |
| Errored | Prefix replay, then a terminal `RUN_ERROR` |

Rendering notes: history comes from `chat_history`; the in-progress run's content comes only from the reattach stream, so there is no overlap. The replayed prefix arrives as one idempotent `MESSAGES_SNAPSHOT` (AG-UI events carry no sequence numbers, so replace-semantics snapshot replay is used instead of a cursor), then live deltas continue on the same message IDs. A fresh page renders correctly with no special handling; on an in-place SPA reconnect, clear the run's rendered messages first and let the snapshot rebuild them. Multiple tabs may subscribe to the same run concurrently.

Operational notes: `active_run` and auto-resolution report only PENDING/RUNNING runs whose event stream is still live — a PAUSED run waits on human input and follows the HITL resume flow, and stale RUNNING rows left by a server restart are filtered out, so the field's absence reliably means "settled history". Runs keep executing after disconnect, so a "stop generating" button must call `POST /agents/{agent_id}/runs/{run_id}/cancel`. Run state lives in memory (or Redis, with the Redis event-stream backend, which also makes reattach work across replicas).

## Frontend tools and backend HITL are different

These two pause patterns look similar in a UI but have different ownership:

| Pattern | Where the tool exists | Who executes it | Example |
|---|---|---|---|
| Frontend-defined tool | The client sends its schema in `RunAgentInput.tools`; there is no Python implementation on the backend. | The browser executes it and sends a trailing AG-UI tool message with the result. | `agent_with_tools.py` |
| Backend confirmation | Python registers a real `@tool(requires_confirmation=True)` implementation. | AgentOS persists the paused run; the frontend sends `{"accepted": true}` or a rejection, then AgentOS resumes and conditionally executes Python. | `human_in_the_loop.py` |

The backend pause/resume mechanics themselves (`requires_confirmation`,
`continue_run`, `@approval` records) are taught in
[`../05_human_in_the_loop/`](../05_human_in_the_loop/); this folder covers only
how AG-UI surfaces them.

For example, a CopilotKit frontend can provide `change_background` in the
request:

```json
{
  "name": "change_background",
  "description": "Change the page background to a CSS value.",
  "parameters": {
    "type": "object",
    "properties": {"background": {"type": "string"}},
    "required": ["background"]
  }
}
```

The AG-UI adapter converts that request-scoped definition into an
`external_execution` function with no server entrypoint. The first stream
returns its tool-call ID; after the browser performs the change, it sends a
trailing tool message with that ID to resume the persisted run. By contrast,
the email function in `human_in_the_loop.py` is present and executable on the
server, but cannot run until its confirmation requirement is resolved.

## State and media

AG-UI state is a dictionary sent with the request. `shared_state.py` snapshots
that dictionary before the run, lets `update_session_state` mutate it, emits a
JSON Patch delta after the tool call, and finishes with an authoritative
snapshot.

Media belongs in the latest user message as an AG-UI image, audio, video, or
document content part. The adapter converts URL or base64 data sources into
Agno media objects before calling the Gemini agent in `agent_with_media.py`.
