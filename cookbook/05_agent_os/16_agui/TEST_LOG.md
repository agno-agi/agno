# Test Log: 16_agui

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.

The OpenUI addition was tested on 2026-08-18 against Agno source commit
`32e5fb9c2203fa98de19ca72750133a57a075899`.

`background_run.py` was re-tested on 2026-09-04 and last re-confirmed on
2026-09-08 against the tree of the commit that carries this entry, on a machine
with no `OPENAI_API_KEY`. That run is scoped accordingly and its entry says what
it could not reach. The entry was rewritten from scratch because the previous
one, written against `8f76f52f41b4366dce9b6def7f4f687ede6c5229`, described
paused-run continuation behavior that has since changed.

Each checked-in server was first booted on its default port 7777. The sweep
asserted `GET /health`, `GET /config`, every mounted AG-UI status route, and a
clean shutdown. Capability-specific POST tests then used
`AGENT_OS_PORT=8877` so they could run independently of concurrent phase work;
the checked-in examples retain the required default port.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Booted the minimal AG-UI server, checked `/health`, `/config`,
and `/status`, then sent a real `RunAgentInput` to `POST /agui`.

**Result:** Health returned `ok`; config returned OS `agui-basic-os`, agent
`agui-assistant`, and one AG-UI interface at the empty prefix. The SSE stream
started with `RUN_STARTED`, ended with `RUN_FINISHED`, and produced the text
`AG-UI stream verified`.

---

### agent_with_tools.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Exercised one Python backend tool and one client-supplied
frontend tool, including the external-execution resume round trip.

**Result:** Health and `/tools/status` passed; config returned
`agui-tools-os` and `agui-tools-agent`. `get_weather("London")` emitted
`TOOL_CALL_START`, `TOOL_CALL_RESULT`, and a final answer. A request-scoped
`change_background` schema paused without a tool result at call
`fc_01fa1d4aa4e1af91006a62d93d320c8191bee4a9476e4a4eba`; a trailing AG-UI
tool message resumed the same thread and completed with
`Changed the background to navy.`

---

### structured_output.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Requested a lunar mystery through the structured-output
AG-UI route and parsed the streamed model response as JSON.

**Result:** Health and `/structured-output/status` passed; config returned
`agui-structured-output-os` and `agui-script-writer`. The stream completed with
the title `The Mare Tranquillitatis Silence` and exactly the schema fields
`characters`, `genre`, `setting`, `storyline`, and `title`.

---

### reasoning_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Sent the bat-and-ball problem to the reasoning AG-UI route
and inspected both reasoning and answer events.

**Result:** Health and `/reasoning/status` passed; config returned
`agui-reasoning-os` and `agui-reasoning-agent`. The stream contained
`REASONING_START`, `REASONING_MESSAGE_START`, 660 characters of reasoning
content, `REASONING_MESSAGE_END`, and `REASONING_END`, followed by the correct
answer that the ball costs `$0.05`.

---

### agent_with_media.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Sent a generated 64-by-64 red PNG as an inline base64 AG-UI
image part to the live Gemini agent.

**Result:** Health and `/media/status` passed; config returned
`agui-media-os` and `agui-media-agent`. `gemini-3.5-flash` received the
186-byte image and the completed event stream answered
`The dominant color in this image is red.`

---

### shared_state.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Supplied initial recipe state and asked the agent to update it
through `update_session_state`.

**Result:** Health and `/shared-state/status` passed; config returned
`agui-shared-state-os` and `agui-recipe-agent`. The stream emitted an initial
`STATE_SNAPSHOT`, a `STATE_DELTA` after the tool result, and a final snapshot.
Delta paths included `/recipe/title`, two ingredient paths, and two instruction
paths; the final title was `Quick Tomato Soup`.

---

### human_in_the_loop.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Asked the live agent to call the backend `send_email` tool,
confirmed the paused requirement through a trailing AG-UI tool message, and
observed the continued run.

**Result:** Health and `/human-in-the-loop/status` passed; config returned
`agui-hitl-os` and `agui-email-agent`. The first stream exposed confirmation
tool call `fc_0555339da3dade57006a62d9a7a6388191a2c63cd5b0cebfd6` without
executing it. Sending `{"accepted": true}` resumed the persisted run, emitted
the tool result, and completed with the recipient `ops@example.com` and subject
`Test Alert`.

---

### research_team.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Asked the Team to delegate current AG-UI research to the
Researcher and synthesis to the Writer.

**Result:** Health and `/research-team/status` passed; config returned
`agui-research-team-os` and team `agui-research-team`. The 604-event stream
included delegation and web-search tool events, member output, source links,
and a final two-fact brief before `RUN_FINISHED`.

---

### multiple_instances.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Booted both interface mounts, checked both status routes, and
sent one request through each prefix.

**Result:** Health passed; config returned `agui-multiple-os`, agents
`agui-chat-agent` and `agui-analyst-agent`, and AG-UI routes `/chat` and
`/analyst`. Both status routes returned `available`. `/chat/agui` returned a
one-sentence API definition, while `/analyst/agui` returned three labeled
points, and both streams closed with `RUN_FINISHED`.

---

### background_run.py

**Status:** PASS (routing, cursor stamping, and resume gating only; no model
call, so this is not a full-capability PASS like the entries above)

**Test mode:** LIVE SERVER, NO MODEL KEY

**Description:** Booted the checked-in server on its default port 7777 with no
`OPENAI_API_KEY` in the environment, and with `PYTHONPATH` pointed at this
worktree's `libs/agno` so the AG-UI interface under test is this tree's and not
another checkout's editable install. Checked `/health`, `/config`, and
`/background/status`, then sent ten `POST /background/agui` requests: a
background opt-in, two reconnections with the same `runId` from different
resume positions, a reconnection naming a `runId` no run uses, a second
background run seeded on a different thread plus a cross-thread reconnection to
it, a resume position with `enabled` set to `false`, two paused-run
continuations echoing a resume position, and a plain foreground run.

**Result:** Health returned `ok`; config returned OS `agui-background-os`,
agent `agui-background-agent`, model `gpt-5.6-luna`, database
`agui-background-db`, and one AG-UI interface at route `/background`;
`/background/status` returned `available`.

The background opt-in, sent as `forwardedProps.agnoBackground` set to the
boolean `true` shorthand rather than the `{"enabled": true}` form the README
documents, streamed five events. Both spellings are accepted. `RUN_STARTED` and `STATE_SNAPSHOT` came at cursors
`{"eventIndex": -1, "subIndex": 0}` and `{"eventIndex": -1, "subIndex": 1}`,
the snapshot carrying the submitted state. Two buffered Agno events with no
AG-UI handler arrived as `RAW` at cursors 0 and 1, wrapping `RunStarted` and
`ModelRequestStarted`. The stream ended at cursor 2 with a `RUN_ERROR` reading
`OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.`

Reconnecting with the same `runId` and `lastEventIndex` 1 replayed exactly one
event, the `RUN_ERROR` at cursor 2. Reconnecting with the same `runId` at
`lastEventIndex` -1 and `lastSubIndex` 0 replayed four events, everything from
the `STATE_SNAPSHOT` at cursor -1/1 onward, dropping only the `RUN_STARTED` at
-1/0. The cursor filter therefore discriminates within one event index as well
as across indices.

A reconnection sending `lastEventIndex` 1 with `runId` `agui-bg-run-other`,
which no run uses, was refused with `Run agui-bg-run-other not found in this
session`, and that refusal was itself stamped at cursor 2, one past the
position the client sent. A second background run `agui-bg-run-2` was then
started on thread `agui-bg-thread-2`; reconnecting to it from thread
`agui-bg-thread-1` with `lastEventIndex` 0 was refused the same way, with
`Run agui-bg-run-2 not found in this session` stamped at cursor 1. Every
refusal observed carried a resume marker one event index past the client's own.

A resume position sent as
`{"enabled": false, "lastEventIndex": 1, "lastSubIndex": 0}` was refused before
anything ran, with `A resume position was sent with background execution
disabled` stamped at cursor 2.

A paused-run continuation, meaning a request carrying a trailing AG-UI tool
message, was not refused. With `agnoBackground` carrying `lastEventIndex` 1 the
server logged the warning `Background execution does not apply to a paused-run
continuation; continuing in the foreground` and took the foreground
continuation path, emitting `RUN_STARTED`, `STATE_SNAPSHOT`, and then
`RUN_ERROR` reading `No paused run matching the provided tool results found in
session agui-bg-thread-1`. None of those three events carried any
`agnoBackground` metadata. The same continuation with `agnoBackground` set to
`true` and no resume position behaved identically. That terminal error is the
continuation finding no paused run to resume in this key-less environment, not
a background refusal.

A plain foreground run with empty `forwardedProps` produced the same five-event
shape as the opt-in run, but with no `agnoBackground` key on any event, so the
resume marker appears only on background responses.

The server shut down cleanly on SIGINT.

**Changed since the previous entry:** the previous version of this entry
recorded a paused-run continuation carrying a resume position as being refused
with `Background execution does not apply to a paused-run continuation` and
starting nothing. At this commit it is not refused. The router decides the
continuation downgrade before it decides the resume gate, so that sentence is
now only a server-side warning and the continuation proceeds in the foreground.

**Not verified:** everything that needs a model call. No assistant text was
produced, so no long-running stream was disconnected and resumed mid-run, no
`TEXT_MESSAGE_*` or tool-call events were ever buffered or replayed, the
terminal `STATE_SNAPSHOT` and the absence of mid-run `STATE_DELTA` events were
not observed, and the buffer-overflow replay refusal was never reached. Those
behaviors are read from `agno/os/interfaces/agui/background.py` rather than
witnessed here. A genuinely paused run was also never reached, so the
foreground continuation path was observed only as far as its "no paused run"
rejection.

---

### openui/server.py and frontend

**Status:** PASS

**Test mode:** LIVE and AUTOMATED

**Description:** Booted the OpenUI AgentOS server and React client, sent live
chart, follow-up, validated-form, form-submission, and backend-tool requests,
then ran the frontend parser, request-contract, type, and production-build
checks.

**Result:** `/status` returned `available`. The chart response contained Q1
120, Q2 180, Q3 150, and Q4 240 plus exactly two `FollowUpItem` values. One
follow-up produced one new AG-UI run. The form contained three required fields
and one primary `@ToAssistant` action; a valid submission acknowledged
`Aurora-731`, team size `7`, and `Prioritize accessibility and charts`. The
stored-revenue request emitted `TOOL_CALL_START`, `TOOL_CALL_RESULT`, and a
renderable chart. A regression test also covers Agno's empty tool-parent text
envelope followed by a fast tool result. Five frontend contract tests,
TypeScript compilation, and the Vite production build passed.

---

## Validation

- All 10 standalone files booted, exposed their expected `/status` route, and
  shut down cleanly.
- 9 of the 10 completed a real capability-specific AG-UI POST flow. The
  exception is `background_run.py`, whose entry records what was verified
  without a model call.
- Recursive pattern validation checked all 11 Python files in the folder, the
  10 standalone servers plus `openui/server.py`, with 0 violations.
- Targeted Ruff format and check passed.
- Python compilation, banned-model, stale-route, scope, Unicode/emoji,
  non-PASS status, and `git diff --check` gates passed.
- The legacy `cookbook/05_agent_os/interfaces/agui/` implementation was fully
  consumed or deleted; no listener or generated bytecode was left behind.
- The OpenUI server passed Python compilation, import, Ruff format, and Ruff
  check. Its frontend passed five tests, TypeScript compilation, and a
  production build.
- Repository-wide Ruff, agnoctl mypy, and cookbook pattern checks passed. The
  core Agno mypy step now reports no issues across 1034 source files, so the 27
  pre-existing errors this section previously recorded are no longer present.
