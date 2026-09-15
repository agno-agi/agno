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
| `interrupt_round_trip.py` | Report a pause as a typed AG-UI interrupt and resume it through the protocol's own resume array. |
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

`interrupt_round_trip.py` asks for `emit_interrupt_outcome=True`. The run-level
outcome that turns on needs the AG-UI interrupt-aware run lifecycle from
`ag-ui-protocol` 0.1.19 or newer, and that is the whole floor for that example,
which serves a single agent. Naming the Team member an interrupt was raised
inside, and closing that member's own lane as suspended, needs the AG-UI
subagent lineage events instead, so that half of the round trip has the same
floor as `team_subagent_lineage.py`, which asks for
`subagent_visibility="attributed"`: `ag-ui-protocol` 0.1.21 or newer. The `agui`
extra allows older releases, so upgrade the demo environment if it resolved one;
otherwise the interface refuses the setting it cannot serve at startup. The
higher of the two floors is what the command below installs, so one upgrade
serves both. `demo_setup.sh` builds that environment with `uv venv`, which seeds
no `pip`, so upgrade it the same way the setup script installs into it:

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
.venvs/demo/bin/python cookbook/05_agent_os/16_agui/interrupt_round_trip.py
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
| `interrupt_round_trip.py` | `http://localhost:7777/interrupts/agui` and `http://localhost:7777/interrupts-quiet/agui` | `/interrupts/status` and `/interrupts-quiet/status` |
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

## The interrupt round trip

A paused Agno run is an AG-UI interrupt. The pending tool call the client has to
resolve comes from the pause itself, and what
`AGUI(..., emit_interrupt_outcome=True)` decides is whether the run terminal also
says the run is waiting. It is a boolean, and the two rows below are what it
decides for a pause a client can answer. It decides two further things, each
described where it belongs: a pause nothing can answer ends the run rather than
waiting, under [A pause no client could answer](#a-pause-no-client-could-answer),
and a Team member the run paused inside has its own lane closed as suspended,
under [A member the run paused inside](#a-member-the-run-paused-inside).

Three pauses reach the client with no call to act on, and each is logged rather
than passed off silently. A pending call carrying no tool call id or no tool name
cannot be rendered, so it is dropped and said so; a pause whose every pending call
went that way prompts with an assistant message and no call under it, which says
the run is waiting rather than finished. A pause no pending call is read from at
all prompts nothing, the run's own words included, so with the outcome off it
reaches the client as a plain finished run: under the default
`subagent_visibility="inline"` that is a pause reported by an Agent whose only
pending call arrives through the run's active requirements, which is what the
visibility table below states. With the outcome on, that pause is still reported
as one: the terminal is built from the run's own open requirements, which are
read under every visibility, so the client is told the run is waiting even where
the prompt shows it nothing to act on. The third needs the outcome on rather than
off, and prompts nothing because the run does not wait at all: a pause nothing
can answer ends as `RUN_ERROR` before any prompt is built.

| Value | What the run terminal carries |
|---|---|
| `False` (default) | `RUN_FINISHED` with no `outcome`, which is what this interface sent before the interrupt-aware lifecycle existed. A pause and a completion are indistinguishable on it, so a client tells them apart by a pending tool call with no result, which is the pause's own prompt rather than anything this setting adds. |
| `True` | `RUN_FINISHED` with `outcome: {"type": "interrupt", "interrupts": [...]}`, one entry per requirement the pause left open, and not one per pending call the prompt showed. Those two lists differ three ways, and the requirement is what the entries are counted by in each: a call the pause carries on two of its own lists at once is prompted once per listing and is still one requirement, so it is one entry; a call the client already has a start for is left out of the prompt and still gets its entry, because it is no less open for that; and a call that could not be rendered is dropped from the prompt and still gets its entry, carrying the tool call id where that call had an id of its own and none where it did not. A pause that reports no requirement at all has nothing else to key an entry by, so there the entries fall back to the pending calls the prompt read, one per call, keyed by the tool call; such a pause whose every pending call could not be rendered keeps the plain terminal, logged rather than dressed up as a completion. A completed run's terminal is unchanged: the setting speaks about pauses only. |

`False` is the default because a client released before that lifecycle stops
sending its own resume directive the moment it sees the structured outcome,
which strands the run. Turn it on for a client that resumes through
`RunAgentInput.resume`.

Each interrupt maps one of Agno's four pause kinds onto the protocol:

| Agno pause | `reason` | Companion fields |
|---|---|---|
| `@tool(requires_confirmation=True)`, a `confirmation` pause | `tool_call` | `toolCallId`, and a `responseSchema` of `{"accepted": boolean, "note": string}`, whose `required` names `accepted` alone. The `note` carries a `description` saying what it is for: Agno records one on a denial, where the model reads it as why the call was refused, and its approval path keeps none, so one sent with an approval is dropped and said so in the server log. No `editedArgs` is offered, because advertising that field is what tells a client it may offer edit UI, and this interface has no way to apply edited arguments. |
| `@tool(external_execution=True)`, an `external_execution` pause, and every frontend-defined tool | `tool_call` | `toolCallId` only. The client runs the tool and hands back whatever it returned, so there is no answer shape to describe. Its `metadata.agno` also carries an `error_report_path`, described under [Resuming](#resuming), and it is the one of the four kinds that does; an entry with no kind behind it carries none either. |
| `@tool(requires_user_input=True)`, a `user_input` pause | `input_required` | `toolCallId`, and a `responseSchema` of `{"values": {...}}` built from the tool's declared input fields, with `values` itself `required`. Each field carries the `type` Agno declared for it, where that is one of the JSON types this interface maps, and its `description` where it has one; a field whose declared type is not one of those is advertised with `not: {"type": "null"}` instead, because a schema an untyped field satisfies is one a null satisfies, and a null is not an answer. The inner `required` names only the fields still without a value: `requires_user_input` is that boolean and nothing more; the separate `user_input_fields` list names the fields withheld from the model, so a field the model was allowed to fill and did fill is described here but not required. |
| `UserFeedbackTools`, the `ask_user` tool, a `user_feedback` pause | `input_required` | `toolCallId`, and a `responseSchema` of `{"selections": {question: [label]}}` built from the questions, with `selections` itself `required`. Each question is an `array` whose `items` are a `string`, carrying an `enum` of that question's own labels where it declares any and no `enum` at all where it declares none, since a client offered an empty list of labels is told nothing rather than told to pick from nothing. Every question carries `minItems` of 1, because an empty array satisfies a required question while telling the model nothing. A single-select question also carries `maxItems` of 1, so a client cannot offer a choice the agent would have to reject, and a question with a header carries it as the array's `title`. The inner `required` names only the questions still unanswered. |

`reason` carries the protocol's own core values, which a client switches on to
pick a surface. Two of the four share `tool_call` and ask for opposite things,
approve this call or run it yourself, so the exact kind and the waiting tool's
name travel beside it in `metadata.agno`. The kind is the one the requirement the
entry was keyed by declares, and one case has no such requirement to read: a
pause reporting none at all falls back to the pending calls, as the table above
says, and for an entry keyed that way no `pause_type` is written and no
`error_report_path` with it. Nothing in such a pause says which of the four kinds
it is, and a kind picked for looking plausible is wrong three times out of four
and acted on every time: an approval published as an external execution is a tool
the client is told to run itself. What that entry carries is what the pause did
report, the proposed call: the `tool_call` reason such a call is shown under, the
call's own id as both the entry's id and its `toolCallId`, the tool's name as the
whole of its `metadata.agno`, and no `responseSchema`, since there is no
requirement behind it to describe an answer. A pause reporting even one
requirement keys every entry by a requirement, so it is never affected. No
`message` is set: the paused run's own words, where it had any, are already on
the wire as the assistant message the pending call is parented to. Where a
visibility withholds them, because they are a member's rather than the run's,
the interrupt does not carry them either: a prompt is not licence to send a
member's words as the run's own reply.

An advertised schema is not decoration, and it is not a validator either. It
describes the answer in full so a client can hold itself to it before it
submits, while the resume side checks the narrow thing it must: that a value
under a described key is of the kind that key was described as. Three keywords
are read for that, `type`, `properties` and `items`, while three are
deliberately left to somebody else: `required` is whether the answer fills the
pause, which Agno answers across the whole requirement and the resume guard
below reports, and `description` and `title` are there for a renderer to show.
The last two of the three exist only so the first is reached wherever a schema
states one: a declared type lives one envelope down under a field's name, and
one more down under the entries of an array, which is where a question describes
its labels. The rest describe
the answer without refusing one, so a client that does not validate can resolve
a pause with an empty selection array, with more labels than a single-select
question offers, or with a label that question never listed. An answer of the
wrong kind under a described key is refused, which is what keeps a client's
object out of a field the run records a string in, and a number out of the
selections the run hands back to the model as the options somebody chose.

A resume that fills nothing still cannot continue the run: the values are
written on, the requirement stays unanswered, and the guard below stops the
resume. A null under a described key the pause does not require is not refused
either. JSON has one way to say there is no value, so that key is read as
unanswered and dropped, which is what keeps a resume possible for a field the
model had already filled.

Only the resume array is read this way. A client answering through a trailing
tool message, which is the channel Agno served before any of this, is held to
nothing it was never shown: the payloads that channel took, a value of another
kind under a declared field among them, are the payloads it still takes, and a
decision it cannot read declines the proposed call there rather than failing the
run.

The `id` of an interrupt is the id of the Agno requirement waiting on it, which
is stored with the paused run and survives the reload the resume reads it back
through. A release that stores no id with the requirement falls back to the tool
call that requirement is waiting on, which is unique within the run for the same
reason the tool call events can be keyed by it. That tool call is the key for the
whole pause as well, and only for a pause reporting no requirement at all: there
is then nothing else to key an entry by, and the entries are the pending calls
the prompt read. A pause that reports even one requirement is keyed by its
requirements throughout, so a listed call with nothing open behind it is not an
entry at all.

### A pause no client could answer

A resume has to answer every requirement the pause left open, or the guard that
reads them stops the run, so one requirement no answer could resolve makes the
whole pause a dead end however answerable the rest of it looks. With the outcome
on, such a pause ends the run rather than waiting: the terminal is `RUN_ERROR`
under the code `pause_not_continuable`, which is this interface's own name in the
field the protocol keeps for one, so a client can tell that case from a run that
died while working without reading the message. The message names each stranded
requirement, the tool it waits on, the interrupt id it would have carried where
it had one, and why nothing resolves it.

The answerable remainder is not advertised and the pending calls are not
prompted, because advertising it is what stranded such a run before: the client
answered everything it was told about and the resume was refused over a
requirement it was never told about, with nothing on the wire having said why. A
client that answers such a pause anyway is refused in those same words, appended
to the partial-resume refusal.

A requirement reaches that state by carrying no id an answer could be keyed to;
by sharing its id with another open requirement of the same pause, where one
answer could only ever resolve one of the two; by being answered through the one
resolver its pause kind picks when that is not what it is waiting on, which is
what a call flagged for two pause kinds at once reports; by having that
resolver's answer leave another of its own answers open; or by asking for input
or feedback with no field or question to put an answer in, or none an answer
could be keyed to. With the outcome off this interface advertises nothing and
makes no claim about what a resume must carry, so it prompts such a pause like
any other. A client that then answers through the resume array is refused by the
guard on it, in those same words. The older tool-message channel runs no such
guard, because merging tool messages leaves a requirement the client sent no
result for untouched and wiring it in would make that an error for every existing
caller, so there an unanswered confirmation is declined at dispatch instead.

### Resuming

The pause arrives on the first request:

```bash
curl -N http://localhost:7777/interrupts/agui \
  -H 'Content-Type: application/json' \
  -d '{
    "threadId": "agui-readme-interrupt-thread",
    "runId": "agui-readme-interrupt-run",
    "state": {},
    "messages": [
      {"id": "message-1", "role": "user", "content": "Email ops@example.com about the outage."}
    ],
    "tools": [],
    "context": [],
    "forwardedProps": {}
  }'
```

The next request carries the answers, on the same `threadId` as the request that
paused. A `threadId` is the Agno session id, so a different one starts a fresh
session rather than resuming the paused run:

```bash
curl -N http://localhost:7777/interrupts/agui \
  -H 'Content-Type: application/json' \
  -d '{
    "threadId": "agui-readme-interrupt-thread",
    "runId": "agui-readme-interrupt-resume",
    "state": {},
    "messages": [
      {"id": "message-1", "role": "user", "content": "Email ops@example.com about the outage."}
    ],
    "tools": [],
    "context": [],
    "forwardedProps": {},
    "resume": [
      {"interruptId": "<the id from RUN_FINISHED>", "status": "resolved", "payload": {"accepted": true}}
    ]
  }'
```

The paused run continues rather than restarting: the resumed stream carries
`TOOL_CALL_RESULT` for the tool call the pause reported, not a fresh proposal of
the same call under a new id.

That array is read whether or not the outcome is emitted, so accepting it does
not depend on the setting. Filling it does: no interrupt id reaches the wire
unless the outcome carries it, so a client talking to a server with the outcome
off has no id to key an entry by and resolves the pause through the trailing
tool message of the older channel instead. A request carrying both the array and
those tool messages is resumed from the array, because that is the one of the
two that names the interrupts the run reported.

Rules worth knowing before writing a client against it:

- One array addresses every open interrupt of the interrupted run. Answering
  some of them stops the run, because an unanswered confirmation reaching
  dispatch is read there as a refusal the client never gave.
- A trailing tool result is keyed by the tool call, so it answers every open
  requirement waiting on that call. Where a request leaves two of them open
  under one call and reports a result for it, the whole request is refused
  naming both interrupt ids: one answer resolving two would read as a pause
  fully answered. Answering each by its own id in the array is what such a pause
  takes. A request carrying no array is not held to this, because that channel
  answered by tool call before any interrupt id existed to answer by.
- A denial is `status: "resolved"` with a negative payload, for example
  `{"accepted": false, "note": "wrong recipient"}`. The protocol's own approval
  example names that field `approved`, and a payload using either name resolves.
  The note is the denial's: an approval keeps none, because Agno's approval path
  stores none and nothing downstream could read one.
- `status: "cancelled"` is a client that abandoned the question. A confirmation
  is then declined and a client-run tool reports back as a failure, so the model
  learns the tool did not run. A pause waiting on structured input cannot express
  it at all, since there is no value that stands in for data the tool needs, and
  the run stops with that reason instead. Those two are the only statuses the
  protocol declares, and an entry carrying a third never reaches the run at all:
  the route validates the whole body against `RunAgentInput` before it is
  handled, and the protocol types that field as those two words, so the request
  is refused as an HTTP 422 naming the entry and the field. No stream opens, so
  a client that handles a stopped run in band sees nothing of this one, not even
  a `RUN_STARTED`.
- A cancelled entry can say why the client gave up, in the same `metadata`
  envelope a failure report uses. The reason joins the cancellation in what the
  run records, as the declined call's note or the failed call's result, rather
  than replacing it, and the run still stops on a pause waiting on structured
  input, naming the reason. The envelope is read the same way under either
  status, so a report that is not a non-empty string stops the run on both.
- A client whose own tool raised says so on a `resolved` entry, under
  `metadata: {"agno": {"error": "why it failed"}}`. That is envelope data about
  the response rather than the answer, which is why it is not in the payload:
  there it would reach the model as the output of a tool that never ran. The
  interrupt for a client-run tool advertises the path in its
  `metadata.agno.error_report_path`, because nothing else on the wire says the
  convention exists. A client-run tool then reaches the model as a failed call, a
  confirmation is declined with the reason as its note, exactly as an errored
  trailing tool message has always been read, and a pause waiting on structured
  input has nowhere to put it, so the run stops with the reason as a cancelled
  one does. The report has to be a non-empty string; anything else stops the run
  rather than being dropped, which would store the payload beside it as a result
  and tell the model the tool ran. The entry's `metadata` was declared by the
  protocol in `ag-ui-protocol` 0.1.21, and the envelope works below that release
  as well: a resume entry accepts keys it does not declare and keeps them as
  extra data, and this side reads the report off the entry rather than off a
  declared field, so a client on the floor the Prerequisites name reports a
  failure the same way and the run records it the same way.
- A `resolved` entry for a client-run tool has to carry what it resolves it
  with. No payload and no reported failure is refused: a tool that returned
  nothing says so with an empty payload, and a client that ran nothing cancels
  instead.
- An `interruptId` the run does not carry is logged as a warning and skipped, and
  is never matched to some other pause. The protocol has a producer proceed
  without an entry it does not recognise rather than fail a run over an answer it
  never asked for, so the entries beside it still answer the interrupts they name
  and the run continues. One for a requirement the run has already resolved is a
  replay of an answer it holds, so it is left alone.
- A whole array that answers no paused run in the session answers nothing: a
  retry, a double submit, or a body replayed after its run was already continued.
  Those entries are unrecognised too, so they are warned about and the request
  runs as the fresh run it otherwise describes instead of failing.
- An answer to an interrupt the run *is* waiting on is a different case. It is
  held to the shape that interrupt advertised, and one this side cannot read
  still stops the run: the pause stays open either way, and a client is owed the
  reason its payload was refused.

A resume request carries the same `context` array as any other, and it reaches
the continued run: tools and instruction templates read it through the run's
dependencies, so changing a value between the two requests changes what they
read. What it does not do is put a context block in the conversation. That block
is written while a user message is built, and a resume continues the paused run
instead of starting a turn, so the model still sees the block the first request
produced.

### A member the run paused inside

Under `subagent_visibility="attributed"`, an interrupt raised inside a Team
member carries that member's `subagentRunId`, and the member's own
`SUBAGENT_FINISHED.outcome` carries `{"type": "suspended", "interruptIds":
[...]}`, so a client renders the member as waiting rather than as work that
finished. A member suspended only because a member below it interrupted is
closed as suspended too, with no interrupt ids of its own.

Both halves are one setting. A lane closed as suspended beside a run terminal
that reports a completion would tell a client the member is waiting on a run
that says it finished, so the suspended outcome is emitted only alongside the
run-level one. The visibilities that name no member attribute nothing here
either: `"hidden"` must not let a confirmation prompt reveal which member asked.

Those two halves also need a later release than the run-level outcome does.
Naming the member on an interrupt is the interrupt's own `subagentRunId` field,
which arrived with the AG-UI subagent lineage events in `ag-ui-protocol` 0.1.21,
while the run-level outcome is served from the earlier release the Prerequisites
name. Asking for `"attributed"` needs those lineage events anyway, so an install
that can attribute an interrupt to a member is one that can name it.

The suspended outcome reached the protocol in that same release as the lineage
events, so an install that can attribute an interrupt to a member can close its
lane as suspended too, and no released version serves one without the other. The
interface still detects the two separately, because they are two things it
writes: an install carrying the interrupt types and the lineage fields but not
the suspended outcome would attribute the interrupt to the member, close its lane
plainly, and say so at startup rather than doing it silently.

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
| `"inline"` (default) | Member work streams as the team's own, exactly as it did before this option existed. No lineage events, no lineage fields. A paused run's own three pending-call lists are read whichever entity reported the pause, an Agent's as much as a Team's. What the default reads on a Team's pause only is the other place a pending call arrives, the run's active requirements, which is how a delegated run and an inner agent report one; so a pause reported by a single Agent whose pending call arrives only that way is prompted with nothing to confirm, and with `emit_interrupt_outcome=False` that is a plain finished run. Turning the outcome on does not change what this setting prompts; the run terminal reports that pause as an interrupt anyway, because the terminal is built from the run's open requirements under every visibility. The other two settings read the requirements on both pause shapes and prompt that call. |
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

Whether that terminal carries an outcome is what `emit_interrupt_outcome`
decides, which [A member the run paused inside](#a-member-the-run-paused-inside)
covers: with the outcome on, a lane this visibility names closes as suspended
and the run's own terminal reports the interrupt outcome beside it, and with it
off neither half goes out. The protocol pairs the two, and a lane closed as
suspended beside a run terminal that reports a completion would tell a client
the member is waiting on a run that says it finished, which is why one setting
owns both halves.

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
