# Test Log: 16_agui

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.

The OpenUI addition was tested on 2026-08-18 against Agno source commit
`32e5fb9c2203fa98de19ca72750133a57a075899`.

The Workflow addition was tested on 2026-09-11 against the tree that adds
`workflow.py` and the AG-UI event-mapping changes it needs. No commit is named
here because that work lands as a single squashed commit whose hash does not
exist while this file is being written.

The 2026-07-24 sweep booted each of the 9 servers the folder held on that date
on its default port 7777, asserting `GET /health`, `GET /config`, every mounted
AG-UI status route, and a clean shutdown. Capability-specific POST tests then
used `AGENT_OS_PORT=8877` so they could run independently of concurrent phase
work; the checked-in examples retain the required default port. `workflow.py`
arrived after that sweep and after the OpenUI boot recorded below, and has never
been booted on a port; its entry below says what was run instead.

Changing an example's shape, step order, or output means updating this file and
`README.md` in the same commit, and no entry here may describe a run that was
not performed.

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

### workflow.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran on 2026-09-11 against the file as it ships after this pass,
which rewrites the `summarize_run` docstring and makes that step report the
failed step names alongside the completed ones. Loaded the example module,
wrapped its `app` in `fastapi.testclient.TestClient` so no port was bound, and
sent a real `RunAgentInput` asking for a small internal status page to `POST
/workflow/agui`. The first two steps run `gpt-5.5` agents; the third runs the
plain Python function `summarize_run`.

**Result:** `/workflow/status` returned `available`, and the POST returned 200
with `text/event-stream`. The stream started with `RUN_STARTED` and ended with
`RUN_FINISHED`. `STEP_STARTED` and `STEP_FINISHED` were balanced across `Plan`,
`Review`, and `Summary`, in that order, matching the step order the file ships.
Each step produced its own assistant message, and the function step's output
arrived as one message reading `Run summary. Steps completed before this one:
Plan, Review.` with no failed-step sentence, since none failed. A
`STATE_SNAPSHOT` bracketed the run at each end. Event and delta totals are model
output and vary between runs, so none is recorded here: two runs of this same
request on the same day totalled 162 and 220 events. The structure above held on
both.

The same run also probed `GET /workflow/agui`, which returned 405 `Method Not
Allowed`, which is why the file's `Try:` line names a POST. Calling
`summarize_run` directly with no `previous_step_outputs` returned `Run summary.
Steps completed before this one: none.`

---

### workflow.py with a failing model credential

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran on 2026-09-11. Same file, same `TestClient` harness, same
request, with `OPENAI_API_KEY` set to an invalid value so both agent steps fail
for real against the provider. This is the case the README's terminal-event rule
has to survive, and the earlier probes of that rule never reached it.

**Result:** Each agent step logged `Step <name> failed (attempt 1)` through
`(attempt 4)` and then failed, which is the default `Step.max_retries` of 3 plus
the initial call. The stream still ended with `RUN_FINISHED`, not `RUN_ERROR`,
because the last step result belongs to the plain Python summary and it
succeeded. `STEP_STARTED` and `STEP_FINISHED` were still balanced across `Plan`,
`Review`, and `Summary`, and the two failed spans carried no `TEXT_MESSAGE_*`
events, so the run's only assistant message was the summary's.

Those spans are not empty. Each failed span carried exactly 8 `RAW` passthrough
events, a `RunStarted` and a `ModelRequestStarted` pair for each of the 4
attempts, every one of them naming its step on `step_name` and its agent on
`agent_name`. An earlier entry here said the two failed spans held nothing and
that the empty pair was the only sign those steps ran; both halves were wrong and
were removed rather than annotated. The README carried the same claim and has
been corrected to match.

Before this pass `summarize_run` reported only the names that succeeded, so this
run made it read `Run summary. Steps completed before this one: none.`, which is
byte-for-byte what a run with no earlier steps produces. It now also names the
failures, and on this run reported `Run summary. Steps completed before this one:
none. Steps that failed: Plan, Review.` The passing run above still reports
`Plan, Review.` as completed and adds no failed-step sentence.

---

## Validation

- The 2026-07-24 sweep covered the 9 standalone files the folder held on that
  date. Each booted, exposed its expected `/status` route, and shut down
  cleanly.
- Each of those 9 files completed a real capability-specific AG-UI POST flow.
- Recursive pattern validation over that 9-file folder checked exactly 9 Python
  files with 0 violations. `openui/server.py` and `workflow.py` arrived after
  the sweep and were verified on their own; see their entries above.
- Targeted Ruff format and check passed.
- Python compilation, banned-model, stale-route, scope, Unicode/emoji,
  non-PASS status, and `git diff --check` gates passed.
- The legacy `cookbook/05_agent_os/interfaces/agui/` implementation was fully
  consumed or deleted; no listener or generated bytecode was left behind.
- The OpenUI server passed Python compilation, import, Ruff format, and Ruff
  check. Its frontend passed five tests, TypeScript compilation, and a
  production build.
- `./scripts/format.sh` and `./scripts/validate.sh` were run again on 2026-09-11
  during this pass, after the `summarize_run` change, and both passed. Validation reported Ruff clean across agno, agnoctl, and
  cookbook, mypy clean over 1033 agno source files and 21 agnoctl source files,
  and the cookbook pattern check clean. An earlier entry here recorded 27
  standing mypy errors in six files; the current tree has none, so that count
  was replaced rather than carried forward. The formatter also rewrote 13 files
  under `libs/` unrelated to this folder; those were restored, leaving only
  this folder's files changed.
- `workflow.py` arrived after the sweep and is verified on its own. Three
  earlier verifications of it were discarded rather than carried forward: one
  described a `Plan`, `Handoff`, `Review` ordering the file no longer has, one
  predated source changes to how a workflow run's ending is judged, and one
  recorded the failed-step rule from probes that never reached the case the rule
  turns on. The two entries above record fresh live runs on 2026-09-11 against
  the file as it ships after this pass.
- On 2026-09-11 the folder holds 10 standalone example servers plus
  `openui/server.py`. Running
  `check_cookbook_pattern.py --base-dir cookbook/05_agent_os/16_agui` on that
  date reported `Checked 10 file(s) in <folder>. Violations: 0`, and the same
  command with `--recursive` reported `Checked 11 file(s) in <folder>.
  Violations: 0`. No new boot or POST sweep was run across all 10 servers on
  that date; the per-file entries above remain the record of what each one
  exercised, and only `workflow.py` was re-run live.
- Unit tests, re-run on 2026-09-11 during this pass.
  `libs/agno/tests/unit/os/interfaces/test_agui_workflow.py` reported 266
  passed, with no xfailed and no skipped. The eight `test_agui_*.py` files under
  `libs/agno/tests/unit/os/interfaces/` were then run together and reported 383
  passed. An earlier entry here recorded 251 and 368 from an earlier state of the
  branch; those were replaced rather than carried forward.
- Integration tests, re-run on 2026-09-11 during this pass with `OPENAI_API_KEY`
  set, since the AG-UI integration modules skip themselves without it. The three
  `test_agui_*.py` modules under `libs/agno/tests/integration/os/interfaces/`, a
  directory that holds five test modules in all, reported 50 passed together, and
  individually: `test_agui_workflow.py` 5 passed, `test_agui_sse.py` 38 passed,
  `test_agui_state_events.py` 7 passed. `test_agui_workflow.py` and
  `test_agui_sse.py` are added by this change.
  `libs/agno/tests/integration/os/test_agui_authorization.py` reported 9 passed.
  An earlier entry here recorded 46 together and 34 for `test_agui_sse.py`; those
  were replaced rather than carried forward.
- The workflow terminal-event behaviour the README describes was checked on
  2026-09-11 through `POST /workflow/agui` with `TestClient`, on throwaway
  workflows built for the check. Which step result decides the run's ending was
  probed both ways. A three-step workflow whose middle step returned
  `StepOutput(success=False, error="disk quota exceeded")` and whose last step
  succeeded opened and closed all three spans and ended with `RUN_FINISHED`.
  Moving that same failing step to the end ended the run with `RUN_ERROR`
  carrying `disk quota exceeded`, no `code`, and no `RUN_FINISHED`. A step whose
  executor raised was invoked 4 times, which is the default `Step.max_retries`
  of 3 plus the initial call, and ended the stream with `RUN_ERROR` carrying
  `the exporter is offline` and no `code`. A run cancelled mid-step through
  `Workflow.cancel_run` closed its open `STEP_STARTED` span and ended with
  `RUN_ERROR`, message `Run cancel-thread-run was cancelled` and code
  `WorkflowCancelled`. The first three of those were re-run during this pass and
  reproduced: a failing middle step still ended with `RUN_FINISHED`, and a failing
  last step still ended with `RUN_ERROR` carrying `disk quota exceeded` and a
  `code` of `None`. That absent `code` is what the README's terminal-event
  paragraph now states; it previously said `RUN_ERROR` carries a `code`.
- LIVE, this pass. A failure inside a container does not end the run. On throwaway
  workflows over `POST /workflow/agui` with `TestClient`, a `Parallel` whose child
  raised, a `Steps` whose child raised, and a `Router` whose chosen step raised
  each ended with `RUN_FINISHED` and balanced step spans, because the container
  caught the child's failure and a later succeeding step became the last result
  the rule reads. The README's rule previously covered only the plain-step case.
- LIVE, this pass. Two endings leave the route's own bare error on the stream
  instead of one the event mapper built. A `Loop` whose child raised, and a
  `Step` carrying `HumanReview(on_error=OnError.fail)` whose executor raised, each
  ended with `RUN_ERROR` carrying the message `the exporter is offline`, a `code`
  of `None`, and no `rawEvent`, with `STEP_STARTED` at 1 and `STEP_FINISHED` at 0,
  so the open span was never closed. This is `run_entity`'s `except Exception`
  handler in `libs/agno/agno/os/interfaces/agui/router.py`, which is pre-existing
  code this change does not touch. The README previously said open spans are
  closed before the terminal error; that sentence was removed rather than
  qualified.
- LIVE, this pass. The scope of the failed-step rule. A plain `Step` and a
  `Condition` default to `HumanReview.on_error` of `OnError.skip`, so a failure
  leaves a failed result and the run carries on, which is the case `workflow.py`
  demonstrates. Read from the source rather than run: in every
  `_aexecute_stream` branch of `libs/agno/agno/workflow/workflow.py` the policy is
  `_step_on_error(step) if isinstance(step, (Step, Condition)) else "fail"`, so
  `Loop`, `Parallel`, `Steps`, and `Router` never consult a policy at all. The
  README previously stated as a general rule that a step exhausting its retries
  does not abort the run. It is true only for a plain step or a condition on the
  default policy, so the rule was cut rather than given its three qualifications.
- LIVE, this pass. Sending a resume message to a workflow re-runs it. Posting a
  trailing AG-UI tool message to `workflow.py` logged `AG-UI cannot resume a
  paused workflow: the tool results were dropped and the workflow is being re-run
  from the start against the last user message`, then opened and closed all three
  spans of `Plan`, `Review`, and `Summary` again and ended with `RUN_FINISHED`.
  The README's pause section previously said only that a workflow pause cannot be
  resumed, and now says what sending one actually does.
- A failure's own `code` was checked on 2026-09-11 by serving a plain Agent over
  AG-UI with an invalid `OPENAI_API_KEY`. The stream ended with `RUN_ERROR`
  carrying the provider's message and the code `model_provider_error`, read from
  the error event's `error_type`. So a `code` is present on a real failure too,
  and only its value separates a failure from a pause or a cancellation. An
  earlier entry here said the presence of a `code` was the discriminator; it was
  removed rather than annotated.
- The workflow pause behaviour documented in the README was checked on
  2026-09-11 over `POST /workflow/agui` with `TestClient`, again on throwaway
  workflows. On a workflow whose single step is a `gpt-5.5` agent holding a
  `requires_confirmation` tool, the stream opened `STEP_STARTED` for the step,
  emitted no `TOOL_CALL_*` event of any kind, left the Python unexecuted, and
  ended with `RUN_ERROR`, message `Workflow paused at step 'Email'` and code
  `StepExecutorPaused`. No `RUN_FINISHED` appeared, so no resume request was
  sent: there was no tool call id to send a decision against. On a workflow
  whose single step carries
  `human_review=HumanReview(requires_confirmation=True)`, the four-event stream
  emitted no `STEP_STARTED` and no `TOOL_CALL_*` event and ended with
  `RUN_ERROR`, message `Workflow paused at step 'Gated'` and code `StepPaused`.
  A `Condition` carrying the same `human_review` gate ended identically under
  `StepPaused`. A `Router` carrying
  `human_review=HumanReview(requires_user_input=True)` ended under
  `RouterPaused`, and a `Step` carrying `requires_output_review=True` ran, closed
  its span, and then ended the run under `StepOutputReview`. Those are the four
  reachable members of the interface's pause-event set, and each was observed
  here; see the source-read entry below for the two that are not reachable.
- Each of those terminal errors carried the whole pause event on its `rawEvent`,
  not just the code: the `StepExecutorPaused` payload included
  `executor_requirements` naming the `send_email` tool call awaiting
  confirmation, and the `RouterPaused` payload included
  `available_choices: ["Left", "Right"]`. An earlier entry here said the code was
  the whole of what a client receives; it was removed rather than annotated.
- Two further earlier entries recorded the opposite of the pause results above,
  describing the step-level gate as reaching the client as a `RAW` `StepPaused`
  event on a stream that still ended with `RUN_FINISHED`, and the agent
  confirmation tool as streaming `TOOL_CALL_START`, `TOOL_CALL_ARGS`, and
  `TOOL_CALL_END`. Neither describes the current tree. They were removed rather
  than annotated, since no entry here may describe a run that was not performed.
- Read from the source rather than run: `WorkflowPaused` and `ConditionPaused`
  cannot reach an AG-UI stream at all, which is why the README no longer names
  them. `ConditionPaused` exists only as a `WorkflowRunEvent` value in
  `libs/agno/agno/run/workflow.py`; it has no event class, is absent from
  `WORKFLOW_RUN_EVENT_TYPE_REGISTRY`, and is constructed nowhere. The run above
  agrees: a `Condition` gate paused under `StepPaused`. `WorkflowPausedEvent` is
  never yielded by `Workflow.arun`; every construction site synthesizes it after
  that generator is drained, on the workflows router's own streamers and on the
  background and continue paths. The AG-UI route consumes
  `entity.arun(stream=True)` directly, so none of those sites is on its stream.
- That a frontend-defined tool is dropped for a workflow was confirmed on
  2026-09-11 by posting a `change_background` schema in `RunAgentInput.tools` to
  `workflow.py`. The server logged `AG-UI client tools are not forwarded to
  workflows`, the stream carried no `TOOL_CALL_*` event, and the run ended with
  `RUN_FINISHED`.
