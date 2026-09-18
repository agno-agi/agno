# Test Log: 16_agui

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.

The OpenUI addition was tested on 2026-08-18 against Agno source commit
`32e5fb9c2203fa98de19ca72750133a57a075899`.

The 2026-09-04 note at the end of this file supersedes the scope of every LIVE
result below: the AG-UI request path itself changed after they were recorded.
Read each section as the result it was, not as a current one. That note carries
its own live results for the two files the change touches.

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

- All 9 standalone files booted, exposed their expected `/status` route, and
  shut down cleanly.
- All 9 files completed a real capability-specific AG-UI POST flow.
- Recursive pattern validation checked exactly 9 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Python compilation, banned-model, stale-route, scope, Unicode/emoji,
  non-PASS status, and `git diff --check` gates passed.
- The legacy `cookbook/05_agent_os/interfaces/agui/` implementation was fully
  consumed or deleted; no listener or generated bytecode was left behind.
- The OpenUI server passed Python compilation, import, Ruff format, and Ruff
  check. Its frontend passed five tests, TypeScript compilation, and a
  production build.
- Repository-wide Ruff, agnoctl mypy, and cookbook pattern checks passed. The
  core Agno mypy step reported 27 existing errors in six files outside this
  integration's diff.

## Update 2026-09-04: conversation history

Changed here: `basic.py` gained `add_history_to_context=True` so the example
continues its conversation instead of answering each turn from scratch;
`stateless.py` is new and serves an agent with no database at all; and the README
gained a section on where history comes from in each case. The AG-UI request path
itself changed too, in turn selection, in what tool traffic is forwarded, and in
how a database-less entity is run, so the LIVE results in the sections above
predate the code they describe.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Booted on port 7777, asserted `/status`, then posted a two-turn
AG-UI conversation on one `threadId` against `gpt-5.5`: "my name is Ada", then
"what is my name?".

**Result:** Status returned available. Turn one answered "Nice to meet you,
Ada!"; turn two answered "Your name is Ada.", so history came from the stored
session. One session row with two runs afterwards.

**Observed, not diagnosed:** the first attempt ran against a `tmp/agui_basic.db`
left behind by an earlier session, and turn two answered "I don't know your
name." That database held one session row and one run row, and turn one's run
was never stored. Deleting the file and repeating gave the passing result above.
Whether a database file from an older run can silently swallow the first run of a
new one is a storage question, outside this change and unexamined here.

### stateless.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Same two-turn conversation on the `/stateless` prefix against
`gpt-5.6-luna`, with no database anywhere in the example.

**Result:** Status returned available. Turn one answered "Nice to meet you,
Ada!"; turn two answered "Your name is Ada.", from the transcript the client
resent rather than from any session.

### Provider-shape checks, in process against `gpt-5.6-luna`

The unit tests use a recording model, which accepts any message shape, so these
six ran against the real API to confirm the forwarded shapes are ones a provider
takes. All passed:

- Two turns with no database: answered "Your name is Ada."
- Two turns with a database: the same, as a control on the untouched path.
- A complete tool block forwarded as history: answered from the tool's result.
- A transcript whose tool traffic is all dropped by the pairing rules
  (unanswered call, reused id, empty result): accepted, no error event.
- A caption-less image in history, which the interface forwards with empty text:
  accepted, and the model described the image.
- A transcript ending on an assistant reply: accepted.

These cover OpenAI's Responses API only. Anthropic and Gemini are argued from
their formatters in this repo, not exercised here.

### Also verified

- `libs/agno/tests/unit/os/interfaces/test_agui_history.py`,
  `test_agui_router.py` and `test_agui_history_invariants.py`, which drive the
  AG-UI request path for an Agent, a Team and a remote entity, with and without
  a database, asserting the exact messages that reach the model, plus the
  ordering, pairing and partitioning properties across twenty-six transcript
  shapes.
- Ruff format and check on the edited and added files, and Python compilation of
  every standalone file in the folder including `openui/server.py`.
