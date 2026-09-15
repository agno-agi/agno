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
| `team_subagent_lineage.py` | Serve one Team twice, attributing each message and tool call to the member that produced it and streaming the same run without attribution. |
| `multiple_instances.py` | Mount two independent AG-UI interfaces on one AgentOS. |
| `openui/` | Render an Agent as streaming charts, follow-ups, and validated forms with OpenUI. |

## Prerequisites

Install the demo environment, then export the provider key used by the file:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...  # agent_with_media.py only
```

`research_team.py` and `team_subagent_lineage.py` also need internet access for
`WebSearchTools`.

`team_subagent_lineage.py` asks for `subagent_visibility="attributed"`, which
needs the AG-UI subagent lineage events from `ag-ui-protocol` 0.1.21 or newer.
The `agui` extra allows older releases, so upgrade the demo environment if it
resolved one; otherwise the interface refuses the setting at startup.
`demo_setup.sh` builds that environment with `uv venv`, which seeds no `pip`, so
upgrade it the same way the setup script installs into it:

```bash
VIRTUAL_ENV=.venvs/demo uv pip install -U 'ag-ui-protocol>=0.1.21'
```

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
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/team_subagent_lineage.py
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
| `team_subagent_lineage.py` | `http://localhost:7777/lineage/agui` and `http://localhost:7777/lineage-inline/agui` | `/lineage/status` and `/lineage-inline/status` |
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

## Team member attribution

A Team run mixes the leader's own output with the output of every member it
delegated to. `AGUI(..., subagent_visibility=...)` decides how much of that
distinction the client sees. The setting concerns delegated runs, and a Team's
members are where they usually come from. A single Agent usually has none, but
a context provider that runs an inner agent inside the outer run is one: that
inner run reports the outer run as its parent, so under `"attributed"` it
becomes a lane of its own, and under `"hidden"` its own output is withheld the
way a member's is.

| Value | What the client receives |
|---|---|
| `"inline"` (default) | Member work streams as the team's own, exactly as it did before this option existed. No lineage events, no lineage fields. A paused run's own three pending-call lists are read whichever entity reported the pause, an Agent's as much as a Team's. What the default reads on a Team's pause only is the other place a pending call arrives, the run's active requirements, which is how a delegated run and an inner agent report one; so a pause reported by a single Agent whose pending call arrives only that way reaches the client as a plain finished run with nothing to confirm. The other two settings read the requirements on both pause shapes and prompt that call. |
| `"attributed"` | The full member surface: `SUBAGENT_STARTED`, `SUBAGENT_FINISHED` and `SUBAGENT_ERROR` per delegation, plus a `subagentRunId` on the events that carry a member's own output: its text messages, its tool calls and their results, its reasoning, and any custom or otherwise unrecognized event it emitted. |
| `"hidden"` | The member surface is withheld: no `SUBAGENT_*` event, no `subagentRunId`, and nothing a member streamed. What the client receives is the leader's own work, its delegation tool call included, and that call's arguments name the member and carry the task text it was given, exactly as the default sends them, followed by the call's result and the leader's own reply. Two things a member caused also reach the client, neither attributed to it: a session-state change one of the member's tools made, because that state is one shared document, and the pending tool call of a member that paused, because the client has to render it to answer, parented to an unattributed assistant message. What that member said while pausing does not reach the client: a prompt is not licence to send a member's words as the run's own reply. A member's failure withholds that same identity: no `SUBAGENT_ERROR`, no stamp, and nothing on it names the member that failed, while the reason the run stopped still reaches the client, because a member's terminal can be the only account the stream carries of how the run ended and is then read as the run's own. The prompt is de-duplicated here, as it is under `"attributed"`, in one case only: a pending call reported both on the paused run's own lists and in a member's requirement is prompted once, carrying the member's attribution. A call the paused run's own lists report twice, by carrying it on two of them at once, is prompted once per listing under every setting, duplicate tool call id and all, because that is the default's stream and the default stream is what it was before this option existed. Under `"attributed"` one more call is left out, a member's own that the client already has a start for; the top-level entity's own pending call is prompted under every setting, so a run with no member on the wire streams what the default streams. |

`"inline"` is the default because a client already in production cannot be
protected after the fact from event types its transport rejects. Opting in is a
deliberate choice by whoever owns the frontend.

Under `"attributed"`, Agno's own run identity is what lineage is built from.
Every streamed chunk reports the run it came from and, for a member, the run
that delegated to it, which maps onto AG-UI as follows:

| AG-UI field | Agno source |
|---|---|
| `subagentRunId` | The member run's own run ID. Agno mints one per delegation, so a member invoked twice occupies two lanes. |
| `SUBAGENT_STARTED.name` | The member's name, or its ID when the chunk carries no name, or the member run ID itself when it carries neither. Each of those is read defensively: a value whose own text cannot be rendered is treated as absent and the next one is tried, so a member with an unreadable name is announced under its run ID instead of ending the run. |
| `SUBAGENT_STARTED.description` | The `task` the delegation call in the `parentToolCallId` row carried, identified by exactly the rule that row states and so absent whenever that call is. Absent too when the call carried no task text: the tasks-mode delegation tools, `execute_task` and `execute_tasks_parallel`, take a task id instead, so a member a task list delegated to has no description rather than an invented one. |
| `SUBAGENT_STARTED.parentSubagentRunId` | The delegating member's run ID for a nested Team. Absent means that no member is named as the parent, so the client places the lane directly under the run itself, and that is the one thing absence means here. It is what a delegation by the top-level team reports; it is also what a member gets when nothing identifies a deeper parent, which includes a member whose first appearance is a pause that no single delegation call can be matched to. It is absent as well when the delegating lane's own terminal has already gone out, because a child must not resolve inside a lane the client has closed, and when this stream has not announced that parent yet: a grandchild's first event can outrun its parent's, and a link to a lane the client has not been given is one it cannot resolve. |
| `SUBAGENT_STARTED.parentToolCallId` | The delegation call the member was spawned inside, when exactly one call identifies it. A call qualifies when it is still open, its tool is one the framework delegates through, and its `member_id` argument names this member. Which calls are searched depends on where the member first appears. For a member that streams, only the delegating lane's own open calls are searched, and exactly one of them has to name the member. For a member whose first appearance is a pause, the open calls of every lane are searched instead, and the one match has to be unique across all of them: two lanes each delegating to the same member therefore yield a link, and a description with it, when that member streams, and neither when it pauses. A lane the announcement cannot name is searched in neither case, and then no link, no parent message and no description is reported at all: that covers a lane whose own terminal has already gone out, and a lane this stream has not announced yet. Falling back to the top-level entity's open calls would hand a grandchild the leader's call, the leader's parent message and the leader's task text as its own description. Absent otherwise: when no open delegation names this member, when more than one does, and when the delegation names no member at all. The broadcast tools, `delegate_task_to_members` and `execute_tasks_parallel`, are that last case, so a member one of them spawned carries no link rather than whichever of the leader's own calls happened to be open. |
| `SUBAGENT_STARTED.parentMessageId` | The assistant message that delegation tool call was parented to. Absent whenever the delegation call is, since the message is read off that call, and absent when that call carried no parent message of its own. |
| `SUBAGENT_FINISHED.result` | The member run's final content, serialized when it is not already text, and absent when the run reported no content at all. A value that neither serialization nor a plain text conversion can render becomes a short note naming its type, so a member that produced something unrenderable still finishes rather than failing the run. |
| `SUBAGENT_ERROR.message` | The member run's error, or the reason it was cancelled, or the interface's own wording when the run reported neither, or reported one whose text cannot be rendered. A cancelled member terminates as an error too, because it produced no result to report, and a lane that errored is never also reported as finished. |
| `SUBAGENT_ERROR.code` | The `error_type` the member run's failure carried, or `"cancelled"` when the member was cancelled rather than failing. Absent when the failure named no type, so a client should treat a missing code as an unclassified failure rather than a successful lane. |

Those last three rows describe a member that reaches its own terminal event.
That terminal is emitted for that member alone: it ends the member's own text
and reasoning spans, so it never lands inside a message, and it ends nothing
else. A member still open when the whole run ends is terminated by the run
instead, deepest lane first. Those two are the only places a member's terminal
comes from. If the run failed, every lane still open is closed with a
`SUBAGENT_ERROR` whose message is the run's error, not the member's, so that
message says why the run stopped rather than what that member did, and which
carries no `code`, because the run's failure is not a diagnosis of that member.
Where the stream itself died rather than the run reporting a failure of its own,
that message is the text of whatever raised, or the name of its type when it
raised without any text, so the lane never errors for no stated reason. If the
run completed or paused, every lane still open is closed with a
`SUBAGENT_FINISHED` that carries no `result`.

A member's terminal can also become the run's own. When a member's failure or
cancellation is the last thing the stream carries, the top-level entity reported
no terminal of its own, so that member's is read as the run's: the run ends with
a `RUN_ERROR` carrying the member's error text, or the reason it was cancelled
under the code `"cancelled"`, rather than with a completion that would report a
run stopped part-way as a success. Which member terminal that is, is simply the
last one the stream carried: nothing ranks a failure above a later completion,
so a member that fails and is then followed by another member completing ends
the run as a completion, and a member that pauses followed by another member
completing loses the pending call it was waiting on. Both hold under every
setting, the default included. A failure ends the run that way under every
setting. A cancellation does so only under `"attributed"` and `"hidden"`, which
are the settings that recognise a member's terminal as a member's: cancellation
is not one of the events that end a run in its own right, so under the default,
where every chunk is the run's own, the same chunk streams as an unrecognized
event and the run still finishes.

A `RUN_ERROR` built from a reported failure also carries the failing Agno event
verbatim in its `rawEvent` field, and which failures come with one depends on
the setting. The top-level entity's own failure supplies it under all three. A
member's does not under `"attributed"` or `"hidden"`: that chunk names the
member, its run, and the run that delegated to it, which is the identity those
two settings exist to attribute or to withhold, so the terminal goes out without
it. Only the default embeds it, whose stream is what it was before this option
existed. A run whose stream died rather than reporting a failure has no such
chunk at all, so its terminal carries only the text of whatever raised.

A member paused awaiting outside input is one of those lanes: pausing is not
finishing, so the member's lane stays open, the confirmation tool calls the
client must render are emitted inside it, and the run-end drain closes it
afterwards. A tool call belongs to the message that carries it, so the two
always name the same member: a member's pending calls are parented to an
assistant message carrying that member's `subagentRunId`, and the leader's own
to an unattributed one. One pause can be waiting on several members at once,
and one message cannot name two, so the prompt is one message per member rather
than one message with everybody's calls under it. Where the pause was reported
by a member rather than by the leader, whatever that member said while pausing
goes out on that member's own message too, and under `"hidden"`, which will not
name the lane, it does not go out at all.

No outcome is attached to that terminal. The protocol pairs a suspended member
with a run-level interrupt outcome, which this interface does not emit, and
sending only the member half would tell a client the member is waiting while
the run reports plain completion.

These are the events that carry a `subagentRunId`:

```text
TEXT_MESSAGE_START TEXT_MESSAGE_CONTENT TEXT_MESSAGE_END
TOOL_CALL_START TOOL_CALL_ARGS TOOL_CALL_END TOOL_CALL_RESULT
REASONING_START REASONING_MESSAGE_START REASONING_MESSAGE_CONTENT
REASONING_MESSAGE_END REASONING_END
CUSTOM RAW
```

Three kinds of event carry none. The `SUBAGENT_*` events name their member in a
dedicated field instead. The `RUN_*` lifecycle events belong to the run as a
whole. And `STATE_SNAPSHOT` and `STATE_DELTA` are left unattributed
deliberately: a team's session state is one shared document, so a client
filtering by member must not lose state written during a delegation.

Message, reasoning, and tool-parent state is tracked per member, so a member's
text never lands in the leader's bubble and two members streaming at once keep
independent spans. Independent spans are interleaved spans: while two of them
are open the wire carries both members' content events mixed together rather
than one whole message and then the next, so a client has to route each event by
the message it names rather than by arrival order. A member's terminal event is
emitted once and is final for the id it names, but it is not a fence. Two things
put events carrying a member after that member's terminal. One is output the
source stream itself produces from a run that has already ended: it stays
attributed to that member rather than being reparented, because giving one
invocation a second lifecycle would be worse than a late event. The other is
this interface's own run-end close, which writes the end of a tool call the
member left open, since a member's terminal ends no tool call: only that call's
own completion carries its result and whatever it wrote to the session state.
Either way a client should keep resolving a member's id after its terminal.

Ordering promises nesting as far as the runs themselves nest: a nested member's
terminal precedes its parent's. A parent run that reports its own completion
while a member it delegated to is still streaming is the exception, because each
terminal goes out when its own run reports one and the member below it is left
to the run end, so that child resolves after its parent. Agno delegates
synchronously, so a run does not normally report the two in that order.

The run end closes what is open before it emits anything of its own. Once the
stream has announced a member lane, it does that in two passes: every reasoning
span and text message still open, children before parents; then every tool call
still open, children before parents; then the pause prompt, if the run paused;
then a terminal for every member lane the run left open. A stream that announced
no member lane has nothing to order across lanes and closes the single lane it
has in one pass instead: its reasoning span, then its tool calls, then its text
message, and then the pause prompt. That is every `"inline"` and `"hidden"` run,
and an `"attributed"` run that never delegated. The difference is visible when a
run ends with both a message and a tool call open: `TOOL_CALL_END` precedes
`TEXT_MESSAGE_END` with no member on the wire, and follows it once there is one.

Either way, nothing the run end emits is nested inside a span, and the pause
prompt in particular opens its message and its tool calls with the delegation
that spawned them already closed. A member whose first appearance is that pause
is announced at the head of the prompt, since a client cannot resolve a call
stamped with a lane it has not been told about. The prompt still precedes the
member terminals, because its calls carry the `subagentRunId` of the members it
is prompting for and nothing may carry a member after that member's terminal.
During the run itself a member's announcement and its own events do sit inside
the still open delegation call: that call is what
`SUBAGENT_STARTED.parentToolCallId` names.

Lineage needs the AG-UI subagent events, which arrived in `ag-ui-protocol`
0.1.21. Asking for `"attributed"` on an older release fails at startup rather
than silently dropping attribution; `"inline"` and `"hidden"` work on any
supported release.

## State and media

AG-UI state is a dictionary sent with the request. `shared_state.py` snapshots
that dictionary before the run, lets `update_session_state` mutate it, emits a
JSON Patch delta after the tool call, and finishes with an authoritative
snapshot.

Media belongs in the latest user message as an AG-UI image, audio, video, or
document content part. The adapter converts URL or base64 data sources into
Agno media objects before calling the Gemini agent in `agent_with_media.py`.
