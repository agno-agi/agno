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
| `background_run.py` | Keep a run alive across a client disconnect and resume it from a cursor. |
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
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/background_run.py
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
| `background_run.py` | `http://localhost:7777/background/agui` | `http://localhost:7777/background/status` |
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

## Background runs and reconnection

By default a run streams inline: closing the connection ends the run. A client
can instead ask for a background run, which executes detached from the request
that started it and buffers its events for replay.

Opt in per request through `forwardedProps`:

```json
"forwardedProps": {"agnoBackground": {"enabled": true}}
```

Every event of a background run then carries its resume cursor:

```json
"metadata": {"agnoBackground": {"eventIndex": 12, "subIndex": 0}}
```

To reconnect, send the same `runId` again with the last cursor received. The
server replays whatever the client missed, once and in order, and then resumes
live streaming until the run finishes:

```json
"forwardedProps": {
  "agnoBackground": {"enabled": true, "lastEventIndex": 12, "lastSubIndex": 0}
}
```

A reconnection has to reproduce the events the first connection would have
sent, which shows up in how state is reported. A request that sends a `state`
is bracketed by a `STATE_SNAPSHOT` when the run starts and another when it
finishes, with no `STATE_DELTA` events in between; a request that sends none
gets neither, exactly as it would streaming inline. A client that follows
shared state along the run, as it can with `shared_state.py`, therefore sees
the state of a background run only as those two snapshots, and has to keep
sending `state` the same way on every connection.

The buffer a background run replays from is finite. A run long enough to
overflow it keeps executing, and a connection that sends no resume position
still gets a well-formed stream starting from wherever the buffer now begins,
with a warning logged naming that event. A reconnection to such a run is refused with a
`RUN_ERROR`: the replay is rebuilt from what the buffer still holds, so a
message whose opening was trimmed would be opened again under a new identifier
while the client's own copy of it was never closed.

A client that never sees the `agnoBackground` metadata cannot resume the run.
That covers both a server too old to offer background runs and a server that
has them but cannot apply them to this particular agent; either way the run
still streams normally on the one connection.

Background execution needs a database, a readable run history so the server can
tell whose run a reconnection is naming, and an agent or team that executes in
this process, so a remote entity cannot use it. What happens
then depends on the request. A first connection runs in the foreground instead,
streaming normally without the ability to resume. A request that carries a
resume position is refused with a `RUN_ERROR` rather than downgraded, because
running it in the foreground would execute the whole run a second time.

Continuing a paused run is not a resume: it starts a new leg, so it always
takes the foreground path and any resume position still being echoed alongside
it is ignored rather than refused.
