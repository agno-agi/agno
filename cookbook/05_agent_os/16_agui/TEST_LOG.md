# Test Log: 16_agui

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.

The OpenUI addition was tested on 2026-08-18 against Agno source commit
`32e5fb9c2203fa98de19ca72750133a57a075899`.

The Team member attribution addition was tested on the attribution branch
itself, across two dates that cover different things. The server boot sweep and
the resolved-visibility checks for `team_subagent_lineage.py` were measured on
2026-09-04. The unit suites named in that entry were re-run on 2026-09-08,
after the review rounds that added
`libs/agno/tests/unit/os/interfaces/test_agui_stream_invariants.py` and changed
what a member's own terminal event closes; that later date is the one the suite
results here describe. The branch is based on Agno source commit
`d1a388446e1b44b20498c772e91303588e2734cf`, which is the base it was written
against and does not contain the work: the results below were measured on the
branch, not on that tree. The branch squashes into one commit whose id does not
exist yet, so the base is the only commit this log can name.

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

### team_subagent_lineage.py

**Status:** PASS

**Test mode:** AUTOMATED

**Description:** Added on 2026-09-04. Booted the two-interface server, checked
`/health`, `/config`, and both status routes, and asserted the visibility each
mounted interface resolved to. No live model turn ran, because this environment
has no provider key; the streamed payloads this file demonstrates are covered
by the AG-UI attribution modules under
`libs/agno/tests/unit/os/interfaces/` instead:
`libs/agno/tests/unit/os/interfaces/test_agui_subagent_lineage.py` for the
attribution surface,
`libs/agno/tests/unit/os/interfaces/test_agui_stream_failure.py` for the
failure path, where a source stream that raises mid-run still has to close
every span and member lane it opened,
`libs/agno/tests/unit/os/interfaces/test_agui_hostile_run_content.py` for run
content no serializer handles cleanly, driven through every boundary that
builds an AG-UI event out of run content,
`libs/agno/tests/unit/os/interfaces/test_agui_documented_contract.py`, which
reads the enumerable claims out of this folder's README and this log and
compares them with the interface's own constants, and
`libs/agno/tests/unit/os/interfaces/test_agui_stream_invariants.py`, which
feeds the shared definition of a well-formed stream a stream that breaks each
invariant in turn and asserts it is reported.

The definition those suites share lives beside them in
`libs/agno/tests/unit/os/interfaces/agui_stream_invariants.py`. It carries no
tests of its own and pytest collects nothing from it; the collectors in the
suites above run it on every stream they gather, and the module named just
above is what proves each of its invariants bites.

**Result:** Health returned `ok`; config returned OS `agui-lineage-os` with
AG-UI routes `/lineage` and `/lineage-inline`. Both status routes returned
`available`. The `/lineage` interface resolved to `attributed` and
`/lineage-inline` to the default `inline`. Every suite named above passed,
under `pytest libs/agno/tests/unit/os/interfaces -k agui`, which also runs the
AG-UI suites that predate attribution. That selector is written instead of a
list of paths on purpose: it names no count and picks the suites up by name, so
it stays correct as suites are added to the folder or removed from it.
Per-suite test counts are deliberately not recorded here either. Tests keep
being added to these suites, so a count written down goes stale while the pass
stays true; run the command above for the current tally.
Wherever a scripted offline model can drive the behavior the assertions run
against a real `Team.run` and `Team.arun` stream: per-member messages and tool
calls, the delegation link, one terminal per member carrying its result, two
members whose runs report identical content staying two lanes, the same member
delegated twice taking a lane and a run id per delegation, the nested-team
parent chain, parallel delegation, a member whose own run fails, the unchanged
inline stream, and a single Agent with no inner run, whose stream the setting
leaves unchanged, pauses included: a pending call one paused Agent reports
twice, by carrying it on two of its lists at once, is prompted once per
listing under all three settings, duplicate tool call id and all, because
that is what the default sends. A team member that pauses is driven from a
real run too: a member whose tool needs a confirmation pauses under a scripted
model, and its announcement and the pending call prompted on its own lane are
asserted against that stream. Reasoning inside a member, output trailing a
member's terminal, a lane whose parent lane terminated before it and a run that
fails with member lanes still open are not reachable from a scripted model, and
neither are the pause shapes a single run cannot produce: a leader and a member
paused at once, a pause naming a member whose lane already terminated, a paused
grandchild, and a pause reported only through requirements. Those cases
hand-build the chunk sequence from the same `run_id`, `parent_run_id`, and
member-identity fields the framework stamps on a member's chunks.

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

- All 11 server files booted, exposed their expected `/status` route, and
  shut down cleanly. The count is every Python file under this folder: the 10
  in its root plus `openui/server.py`, which is the backend half of the nested
  OpenUI example rather than a standalone one. `multiple_instances.py` and
  `team_subagent_lineage.py` each mount two interfaces and exposed both of
  their `/status` routes.
- 10 of the 11 files completed a real capability-specific AG-UI POST flow.
  `team_subagent_lineage.py` was verified without a provider key, so its POST
  flow is covered by the unit suites instead.
- Recursive pattern validation checked exactly 11 Python files, the same root 10
  plus `openui/server.py`, with 0 violations, from
  `python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/05_agent_os/16_agui --recursive`.
  Without `--recursive` that command sees 10 files, so the flag is what makes
  the two counts above comparable.
- Targeted Ruff format and check passed.
- Python compilation, banned-model, stale-route, scope, Unicode/emoji,
  non-PASS status, and `git diff --check` gates passed.
- The legacy `cookbook/05_agent_os/interfaces/agui/` implementation was fully
  consumed or deleted; no listener or generated bytecode was left behind.
- The OpenUI server passed Python compilation, import, Ruff format, and Ruff
  check. Its frontend passed five tests, TypeScript compilation, and a
  production build.
- Repository-wide Ruff, agnoctl mypy, and cookbook pattern checks passed. On
  2026-07-24 the core Agno mypy step reported 27 existing errors in six files
  outside this integration's diff; re-run on 2026-09-08 by `./scripts/validate.sh`
  it reported none, across 1033 Agno source files and 21 agnoctl ones.
- Re-measured on 2026-09-08 against the current tree: `./scripts/validate.sh`
  passed every step it runs, the recursive pattern check saw 11 files and the
  non-recursive one 10 with 0 violations either way, Ruff format and check
  passed on this folder's 11 files, `python -m compileall` and
  `git diff --check` passed, and
  `pytest libs/agno/tests/unit/os/interfaces -k agui` passed on an install
  whose `ag-ui-protocol` serves the lineage events.
- Not re-run on 2026-09-08: the server boots, the per-file AG-UI POST flows and
  the OpenUI frontend checks recorded above, which need the servers started and
  a provider key. Those stand as measured on the dates given with them, and the
  dated line above covers only the checks named in it.
