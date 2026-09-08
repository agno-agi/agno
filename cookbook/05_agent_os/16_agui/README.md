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
| `basic.py` | Mount one agent at the default `/agui` and `/status` routes, reading history from its stored sessions. |
| `stateless.py` | Hold a multi-turn conversation with no database, from the transcript the client sends. |
| `agent_with_tools.py` | Contrast a Python backend tool with a frontend-supplied external-execution tool. |
| `structured_output.py` | Stream a response constrained by a Pydantic output schema. |
| `reasoning_agent.py` | Translate Agno reasoning lifecycle events into AG-UI reasoning events. |
| `agent_with_media.py` | Pass AG-UI image, audio, video, and document parts to Gemini. |
| `shared_state.py` | Send state snapshots and JSON Patch deltas as session state changes. |
| `human_in_the_loop.py` | Pause and resume a real backend tool that uses `requires_confirmation`. |
| `research_team.py` | Stream a coordinated Team and its member activity over AG-UI. |
| `multiple_instances.py` | Mount two independent AG-UI interfaces on one AgentOS. |
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
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/stateless.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_tools.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/structured_output.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/reasoning_agent.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_media.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/shared_state.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/human_in_the_loop.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/research_team.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/multiple_instances.py
```

The [`openui/`](openui/) example includes its own React client. Follow its
README to generate the OpenUI component prompt, run `openui/server.py`, and
start the frontend.

Point an AG-UI client such as CopilotKit or the AG-UI Dojo at the matching
endpoint:

| Running file | POST event stream | Status |
|---|---|---|
| `basic.py` | `http://localhost:7777/agui` | `http://localhost:7777/status` |
| `stateless.py` | `http://localhost:7777/stateless/agui` | `http://localhost:7777/stateless/status` |
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

## Conversation history

AG-UI clients resend the whole conversation on every request, but an Agent or
Team reads history from a session of its own. The interface uses whichever of
those two sources the served entity has:

| Configuration | Where history comes from |
|---|---|
| A database is configured (`basic.py`) | The Agno session named by `threadId`, windowed by `num_history_runs`, which defaults to the newest three runs. Set `add_history_to_context=True` or the model sees only the current turn, and note that a session the database does not have yet is empty history: the client's transcript is not consulted. |
| No database (`stateless.py`) | The transcript in the request. The interface forwards the earlier user, assistant, and tool messages as additional input, and runs the entity with `add_history_to_context=False`, so nothing arrives twice. |
| A `RemoteAgent` or `RemoteTeam` | The remote entity's own session, always. Its run route takes a single message, so the transcript cannot travel with it, and the interface warns when a request carries history it cannot forward. |

The other examples in this folder leave `add_history_to_context` at its default,
because each one demonstrates a capability rather than a conversation. They keep
sessions but do not replay them.

An in-process session cache (`cache_session=True`) is not a third source. It
outlives a request but not the worker, and it belongs to whoever ran that thread
on that worker first, so a database-less entity is always run with its own
history switched off, whether or not the request carries a transcript to forward.

What the forwarding path does and does not do:

- Client `system` and `developer` messages are never forwarded: the entity owns
  its own system message. `activity` and `reasoning` messages are not forwarded
  either, since they carry nothing for the model, and one arriving in the middle
  of a tool exchange does not break the exchange up.
- Only what precedes the current turn is history, and the current turn is the
  newest user message that carries text or media. A transcript that ends on an
  assistant reply asks its newest user message again without replaying that
  reply, and a trailing empty user message does not become the turn unless every
  user message in the transcript is empty.
- Tool traffic is forwarded in the shape providers accept: an assistant turn's
  calls followed immediately by their results. A call whose result does not
  arrive with it is dropped along with the result, a call id is forwarded once
  however often the client reuses it, and a result carrying neither content nor
  an error does not count as one.
- The whole transcript the client sent is forwarded, consecutive turns of the
  same role included, exactly as the client ordered them. `num_history_runs` and
  `num_history_messages` do not apply here: they window a session this path does
  not read, and the first of them defaults to three runs, so applying it would
  silently drop conversation.
- `add_history_to_context` does not gate this path. It selects what a session
  contributes, and this path reads no session.
- Frontend tools and backend confirmations still need a database. Resuming a
  paused run reads it back from the session, so a request carrying tool results
  streams a `RUN_ERROR` event carrying `Frontend tool resume requires a
  database` without one, and `Frontend tool resume requires a local Agent or
  Team` against a remote entity. A remote entity also never receives the
  client's tool definitions; those are dropped with a server-side warning.

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
