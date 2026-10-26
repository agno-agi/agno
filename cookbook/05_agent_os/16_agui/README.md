# AG-UI

AG-UI is an event-stream protocol between an agent backend and an interactive
frontend. AgentOS translates Agent, Team, and Workflow run events into AG-UI
text, tool, reasoning, step, state, and lifecycle events, while keeping the
model, tools, sessions, and approval state on the server.

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
| `workflow.py` | Stream a multi-step Workflow, including a step that runs no model. |
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
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_tools.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/structured_output.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/reasoning_agent.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/agent_with_media.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/shared_state.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/human_in_the_loop.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/research_team.py
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/workflow.py
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
| `workflow.py` | `http://localhost:7777/workflow/agui` | `http://localhost:7777/workflow/status` |
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

The stream begins with `RUN_STARTED` and then emits message or
capability-specific events. A run that succeeds ends with `RUN_FINISHED`. A run
that fails ends with `RUN_ERROR` instead, and so does a workflow run that was
cancelled or that paused. Nothing follows the error.

`RUN_ERROR` always carries a `message`. A `code` and a `rawEvent` are present on
some endings and absent on others: a cancellation carries the code
`WorkflowCancelled` and a pause one of the codes listed in
[Workflows](#workflows) below, while a run ended by a failed last step carries
neither. So read the value where there is one; the presence of a `code` on its
own tells a client nothing.

Tool calls use `TOOL_CALL_*`; reasoning uses `REASONING_*`; shared state uses
`STATE_SNAPSHOT` and `STATE_DELTA`; workflow steps use `STEP_STARTED` and
`STEP_FINISHED`. `threadId` becomes the Agno session ID, so later requests can
continue the same conversation.

## Workflows

`AGUI(workflow=...)` serves a Workflow the same way `agent=` and `team=` serve
their entities. Each step opens a `STEP_STARTED` span and closes it with
`STEP_FINISHED`. A step whose executor is an Agent or Team streams its own text,
tool, and reasoning events inside that span; a step that runs plain Python has
its output emitted as one assistant message, since it streams nothing itself.

A workflow run does not always end with `RUN_FINISHED`. A run cancelled while it
is in flight ends with `RUN_ERROR` carrying the cancellation reason and the code
`WorkflowCancelled`.

When a run reaches its completion event, only the last step result decides. If
that result reports a failure, the run ends with `RUN_ERROR` carrying the reason
that result names. If it reports success, the run ends with `RUN_FINISHED` even
though an earlier step failed and its result says so. A failure inside a
`Parallel`, `Steps`, or `Router` container reaches that same ending from the
other direction: the container catches its child's failure and the run carries on
past it, so a later succeeding step is what the rule reads.

`workflow.py` is easy to catch this on: run it with an invalid `OPENAI_API_KEY`
and both agent steps fail against the provider, yet the stream still ends with
`RUN_FINISHED`, because the last step is the plain Python summary and it
succeeds. A failed step is not silent on the stream. Its span carries a pair of
`RAW` passthrough events for every attempt the step made, each naming the step
and its agent, and the summary step names the failed steps in its own output.

A pause ends the run the same way, and this is the part most likely to surprise
a frontend. No AG-UI pause can be resumed against a workflow, so calling a pause
a finish would tell the client the run is complete when the gated work never
happened. Every kind of workflow pause therefore ends the stream with
`RUN_ERROR`, the message `Workflow paused at step '<name>'`, and a `code` naming
the Agno pause event that ended it: one of `StepPaused`, `StepExecutorPaused`,
`RouterPaused`, or `StepOutputReview`. That terminal error also carries the whole
pause event on its `rawEvent`, so a client that needs the pause's own fields, such
as the tool call awaiting confirmation or a router's available choices, can read
them there.

Sending a resume message anyway is worse than a no-op. The route drops the tool
results and re-runs the whole workflow from the start against the original user
message, logging `AG-UI cannot resume a paused workflow`. What the client gets
back is a second full run, not a continuation of the first.

The pauses a workflow can produce reach that ending by different routes.
`Workflow.arun` takes no run context, so frontend-defined tools cannot be
executed by a workflow and are dropped with a warning, which leaves no
external-execution pause in the first place.

A backend tool marked `requires_confirmation`, held by an Agent inside a step,
opens that step's `STEP_STARTED` span but emits no `TOOL_CALL_*` event of any
kind, so no confirmation card can render. The run ends with `RUN_ERROR` and the
code `StepExecutorPaused`, and the Python behind the tool never executes.

A step-level gate, `Step(human_review=HumanReview(requires_confirmation=True))`,
holds the run before the gated step opens at all: no `STEP_STARTED`, no
`TOOL_CALL_*` event, and the stream ends with `RUN_ERROR` and the code
`StepPaused`. A `Condition` carrying the same `human_review` gate ends the run
the same way and under the same code. A `Router` asking the user to choose a
route ends it the same way under `RouterPaused`, and a step asking for its output
to be reviewed ends it under `StepOutputReview` after that step has run.

Use an Agent or Team for any of these patterns.

## Frontend tools and backend HITL are different

These two pause patterns look similar in a UI but have different ownership:

| Pattern | Where the tool exists | Who executes it | Example |
|---|---|---|---|
| Frontend-defined tool | The client sends its schema in `RunAgentInput.tools`; there is no Python implementation on the backend. | The browser executes it and sends a trailing AG-UI tool message with the result. | `agent_with_tools.py` |
| Backend confirmation | Python registers a real `@tool(requires_confirmation=True)` implementation. | AgentOS persists the paused run; the frontend sends `{"accepted": true}` or a rejection, then AgentOS resumes and conditionally executes Python. | `human_in_the_loop.py` |

Both rows assume an Agent or Team. Neither pattern can be resumed when the
served entity is a Workflow. A workflow pause renders no card at all, since it
surfaces no tool call, and it ends the run with `RUN_ERROR` rather than a
success; see [Workflows](#workflows) above.

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
