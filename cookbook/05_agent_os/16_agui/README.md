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
| `a2ui_generated_ui.py` | Let the agent design its own interface, painted as it streams. |
| `a2ui_fixed_schema.py` | Return a hand-authored interface from an ordinary tool. |
| `multiple_instances.py` | Mount two independent AG-UI interfaces on one AgentOS. |
| `openui/` | Render an Agent as streaming charts, follow-ups, and validated forms with OpenUI. |

## Prerequisites

Install the demo environment, then export the provider key used by the file:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...  # agent_with_media.py only
.venvs/demo/bin/pip install -U ag-ui-a2ui-toolkit  # a2ui_generated_ui.py only
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
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/a2ui_generated_ui.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/a2ui_fixed_schema.py
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
| `agent_with_tools.py` | `http://localhost:7777/tools/agui` | `http://localhost:7777/tools/status` |
| `structured_output.py` | `http://localhost:7777/structured-output/agui` | `http://localhost:7777/structured-output/status` |
| `reasoning_agent.py` | `http://localhost:7777/reasoning/agui` | `http://localhost:7777/reasoning/status` |
| `agent_with_media.py` | `http://localhost:7777/media/agui` | `http://localhost:7777/media/status` |
| `shared_state.py` | `http://localhost:7777/shared-state/agui` | `http://localhost:7777/shared-state/status` |
| `human_in_the_loop.py` | `http://localhost:7777/human-in-the-loop/agui` | `http://localhost:7777/human-in-the-loop/status` |
| `research_team.py` | `http://localhost:7777/research-team/agui` | `http://localhost:7777/research-team/status` |
| `a2ui_generated_ui.py` | `http://localhost:7777/generated-ui/agui` | `http://localhost:7777/generated-ui/status` |
| `a2ui_fixed_schema.py` | `http://localhost:7777/fixed-schema/agui` | `http://localhost:7777/fixed-schema/status` |
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

## Agent-generated interface

An agent can answer with a rendered surface rather than prose. AG-UI carries
that as A2UI: a declarative component tree in a tool result, which the client
draws using components it already knows how to render. There are two ways to
produce one, and they cost very different things.

| | `a2ui_generated_ui.py` | `a2ui_fixed_schema.py` |
|---|---|---|
| Who designs the layout | A render subagent, per question | You, once, in Python |
| Extra model calls | One per attempt | None |
| Component tree | Decided per question | Fixed; only the data changes |
| Needs `ag-ui-a2ui-toolkit` | Yes | No |
| Use when | The shape of the answer varies | You know what the card looks like |

### Asking for generation

Generation is off unless the run asks for it. A client asks by forwarding
`injectA2UITool`. The interface then adds the generation tool for that run and
removes the render tool the client injected, which it replaces.

Alongside that, the client sends the catalog of components it can draw as a
context entry. That entry is what tells the subagent which components exist,
and, unless you pin one with `a2ui={"default_catalog_id": ...}`, it names the
catalog the surface is stamped with. A run that asks for generation without it
still generates, but the subagent designs with no component list and the surface
is stamped with the A2UI basic catalog, which is rarely what the client
registered.

```bash
curl -N http://localhost:7777/generated-ui/agui \
  -H 'Content-Type: application/json' \
  -d '{
    "threadId": "a2ui-readme-thread",
    "runId": "a2ui-readme-run",
    "state": {},
    "messages": [
      {"id": "message-1", "role": "user", "content": "Show me the quarter"}
    ],
    "tools": [],
    "context": [
      {
        "description": "A2UI Component Schema — available components for generating UI surfaces. Use these component names and properties when creating A2UI operations.",
        "value": "{\"catalogId\": \"my-catalog\", \"components\": [{\"name\": \"Column\"}, {\"name\": \"Text\"}]}"
      }
    ],
    "forwardedProps": {"injectA2UITool": true}
  }'
```

That `description` is matched by exact text, so it has to read exactly as
above; an AG-UI client library sends it for you.

To generate for clients that do not ask, pass
`AGUI(agent=..., a2ui={"inject_a2ui_tool": True})`. A client forwarding
`injectA2UITool: false` still turns generation off for its own run.

A tool you wired yourself with `get_a2ui_tools` is never injected over. The
interface reads the `tools` list of the agent or team it was given once per run
and asks two questions of that single reading: whether the entity already
generates surfaces, and whether the generation tool's name is taken.

Every shape a tool reaches that list in answers both. The returned `Function`,
and a `Toolkit` wrapping it, are recognized as generating: injection is skipped,
and the run gets the render channel that paints a surface as it is written. A
plain callable, an OpenAI-style `{"type": "function", ...}` dict, and a flat
`{"name": ...}` dict are read for their names, so a tool of the generation
tool's name is not injected over even when nothing about it generates; a run
against one of those gets no render channel, because nothing server-side is
going to push fragments into it.

One shape cannot be read: a `tools` that is itself a callable the agent resolves
when it runs. Reading it would mean running your code an extra time per request
and handing back tool objects the agent then never sees, so it answers neither
question, and the interface declines instead of guessing. Injection is skipped
with a warning saying why, because a second tool of the same name would leave
the model choosing between duplicates and take the client's render tool away.
Painting is not skipped: the render channel is prepared for any run that might
generate, since an unused channel costs nothing while a missing one loses
progressive painting with nothing to show that it did.

Declining, for any of those reasons, leaves the run exactly as the client
arranged it, and that includes the render tool the client injected: it is not
dropped, so the model is offered both. The client's render tool is an ordinary
frontend tool, so a call to it pauses the run until the browser sends a result
back, the same way `change_background` does in `agent_with_tools.py`. Either
have the client stop injecting it, or expect that pause. The same hands-off path is taken when
generation is asked for and `ag-ui-a2ui-toolkit` is not installed: the interface
logs an error and serves the run with whatever the client sent. A file that
imports from `agno.os.interfaces.agui.a2ui` itself, as `a2ui_generated_ui.py`
does for the tool choice below, does need the toolkit to start at all.

### What the stream looks like

The generation call arrives as an ordinary `TOOL_CALL_*` sequence. Nested inside
it is a second call carrying the design as it is written, one `TOOL_CALL_ARGS`
frame at a time, which is what lets the client show a surface filling in rather
than appearing whole several seconds later. The generation call's result is the
finished surface.

How progressive that is depends on the provider. `OpenAIChat` streams partial
tool arguments; `OpenAIResponses` hands them over in one piece, so the surface
still renders correctly but arrives all at once. That is why
`a2ui_generated_ui.py` uses `OpenAIChat`.

### When the design is wrong

Each attempt is validated against the same rules the client applies, and a tree
that fails is never committed: the errors go back to the subagent and it tries
again, up to three times by default (`a2ui={"recovery": {"maxAttempts": 5}}` to
change that; those keys are camelCase, and a snake_case one is ignored with a
warning). Only a tree that validated becomes the tool result, so a rejected
design never enters the conversation.

A design that never arrives costs an attempt too. One render turn is given 180
seconds by default, and a turn that goes over it, or fails on a provider or
transport error, is recorded as a failed attempt and retried like an invalid
tree. Change that bound with `a2ui={"subagent_timeout": 300}`, or `None` for no
bound at all, remembering that a generation which retries can take a multiple of
whatever you set.

Streaming means a rejected design does reach the client, though. Every attempt's
render call is pushed frame by frame while it is being written, which is before
there is a finished tree to validate. What keeps it off the screen is the client:
the validator the recovery loop retries on is the same one the renderer uses as
its paint gate, so the tree the tool rejects is the tree the renderer refuses to
draw.

If every attempt fails, the tool result is a structured failure carrying no
operations at all, so a surface already on screen is left alone and the
conversation stays usable. When the attempts failed for a reason other than a
bad design, that failure also carries the provider errors under
`subagentErrors`, so a run that died on an expired key does not read as a model
that could not lay out a card.

### Forcing the render call

An attempt that produces no render call at all costs exactly what an invalid
design costs: the loop records that the subagent did not call `render_a2ui` and
spends one of its three attempts. So a subagent that answers in prose burns a
third of the budget before a single tree has been validated.

Forcing the render tool removes that failure mode, and nothing is forced by
default, because no spelling of `tool_choice` works everywhere. Agno hands
`tool_choice` to the provider as it was given: an OpenAI-compatible provider
takes the forced-function object, Gemini reads the same value as a
`function_calling_config.mode` and rejects it, which fails every attempt, and
Anthropic drops `tool_choice` and carries on. Forcing belongs with the model you
picked rather than in a default, which is why the module exports the OpenAI
shape instead of applying it.

`a2ui_generated_ui.py` runs an OpenAI model, so it forces:

```python
from agno.os.interfaces.agui.a2ui import OPENAI_RENDER_TOOL_CHOICE

AGUI(agent=sales_agent, a2ui={"tool_choice": OPENAI_RENDER_TOOL_CHOICE})
```

Wiring the tool yourself puts the same value in the second argument of
`get_a2ui_tools`, which is where the Agno-specific options live rather than in
the cross-framework parameters of the first:

```python
get_a2ui_tools({"model": model}, {"tool_choice": OPENAI_RENDER_TOOL_CHOICE})
```

`subagent_timeout` is passed the same way on either path. A provider that
rejects the object may still accept a plain string: Gemini maps `"any"`,
`"auto"`, `"none"`, and `"validated"` onto its own function-calling modes, and
`"any"` is the one that forces a call.

### A2UI and OpenUI

Both put generated interface on screen, from opposite directions. A2UI is part
of AG-UI: the agent emits components from a catalog the client registered, so
any AG-UI client can draw them. [`openui/`](openui/) is a complete client that
renders an agent's text as components of its own. Use A2UI when the frontend
owns the component library; use OpenUI when you want its client and renderer.
