# Test Log: 16_agui

Runs are identified by their date, what was exercised, and the pinned
dependency versions, never by commit hash: this work rebases onto new upstream
releases, and each rebase rewrites every hash on the branch. The branch's
current upstream base is Agno v3.0.8.

The AG-UI examples were tested on 2026-07-24 and the OpenUI addition on
2026-08-18, each against the branch as it stood then.

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

## A2UI addition, 2026-09-08

Tested against the A2UI addition on this branch, with `ag-ui-protocol 0.1.22`
and `ag-ui-a2ui-toolkit 0.0.4`.

**Test mode:** SCRIPTED MODEL. This environment has no provider key, so each
model turn is scripted at the provider's HTTP boundary. Everything downstream of
that is real: uvicorn, chunked SSE over a real socket, Agno's own streaming
delta parser and tool executor, the AG-UI interface, and the shared A2UI
toolkit's validation and retry loop. A live-model pass is still owed.

### a2ui_generated_ui.py

**Status:** PASS

**Test mode:** SCRIPTED MODEL

**Description:** Booted the server, checked `/health`, `/config`, and
`/generated-ui/status`, then drove four flows over real HTTP: a surface
generated from scratch, an edit whose first design was invalid, an edit whose
every design was invalid, and a run that refused generation.

**Result:** Health returned `ok`; config returned OS `agui-a2ui-os`, agent
`agui-a2ui-agent`, and one AG-UI interface at `/generated-ui`.

Generation streamed: the design arrived as six incremental `TOOL_CALL_ARGS`
frames on a call nested inside `generate_a2ui`, the first naming the catalog the
request forwarded, and the nested call closed before the generation call
reported. The committed surface was the design the model produced, bound to the
forwarded catalog. Ordinary text and tool events were unaffected.

The flow was checked to be genuinely incremental rather than merely ordered: the
render subagent stopped after its first fragment and waited for the client to
confirm that fragment had arrived. Held-back fragments would deadlock instead of
passing.

Recovery held: an invalid design was rejected, its errors were fed back, and the
retry was what got committed. The rejected design never appeared in any tool
result. An edit reconciled the existing surface rather than recreating it.

Exhaustion was clean and bounded: three attempts, then a structured
`a2ui_recovery_exhausted` result carrying no operations at all, so a surface
already on screen was left alone. The run still finished with an ordinary text
answer.

Opting out was clean: with `injectA2UITool: false` the generation tool was never
offered to the model, the client's own render tool was passed through untouched,
no surface was produced, and the answer came back as text. The next request on
the same server, asking for generation, got it.

The README's `curl` example was then run verbatim against the same server and
produced the nested render call, five incremental argument frames, and a surface
bound to the catalog id in the example.

---

### a2ui_fixed_schema.py

**Status:** PASS

**Test mode:** SCRIPTED MODEL

**Description:** Booted the server, checked `/health`, `/config`, and
`/fixed-schema/status`, then asked for a flight over real HTTP.

**Result:** Config returned OS `agui-a2ui-fixed-os`, agent
`agui-a2ui-fixed-agent`, and one AG-UI interface at `/fixed-schema`. The
`show_flight` result was the surface itself: the authored component tree
returned unchanged, the catalog id as written in the file, and only the data
model carrying the call's arguments. Exactly two model turns ran, so no second
model was involved in producing the surface.

---

### Interface tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/os/interfaces/` and
`libs/agno/tests/unit/app/`.

**Result:** green, and green again on every round since.
`./scripts/format.sh` and `./scripts/validate.sh` both clean.

This entry used to carry a count and an inventory of the strict
expected-failures the suites held at the time. Every gap those pinned has since
been closed, each as an ordinary passing assertion, so there is no inventory
left to keep and no reason to record a count here that a later round will
outgrow. The current one is measured in each round's own validation block, most
recently 2026-09-09.

---

## Validation, AG-UI and A2UI addition

- All 11 standalone files booted and exposed their expected `/status` route.
  The 9 that predate the A2UI addition were also checked for a clean shutdown.
- All 11 files completed a capability-specific AG-UI POST flow: the 9 that
  predate the A2UI addition against live models, and `a2ui_generated_ui.py` and
  `a2ui_fixed_schema.py` against a scripted model. A live-model pass for those
  two is still owed.
- Pattern validation checked the folder's 11 top-level Python files with 0
  violations, and 12 with `--recursive`, which adds `openui/server.py`.
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

---

## A2UI docs refresh, 2026-09-08

The render subagent's default tool choice was removed from
`agno/os/interfaces/agui/a2ui.py` after the A2UI addition above was documented:
nothing is forced now, and the OpenAI forced-function shape is exported as
`OPENAI_RENDER_TOOL_CHOICE` for hosts that want it. `README.md` and
`a2ui_generated_ui.py` were brought back in line with that, and the rest of the
A2UI section was re-checked against the current module.

### a2ui_generated_ui.py

**Status:** PASS

**Test mode:** SCRIPTED MODEL. The file now sets
`a2ui={"tool_choice": OPENAI_RENDER_TOOL_CHOICE}`, so what needed checking was
the wiring, not another generation flow. The model was a stand-in driven
in-process rather than scripted at the HTTP boundary. The full generation flows
recorded above were not re-run, and the live-model pass they owe is still
owed.

**Description:** Booted the file's own `app` over real HTTP and asked for
`/generated-ui/status`. Then drove the generation tool on a stand-in model that
records what it is called with: once through `prepare_a2ui_run` with and without
the interface config, and once through `get_a2ui_tools` with and without its
options argument.

**Result:** Status returned `available` with the new interface config in place,
and a run forwarding `injectA2UITool` still injected `generate_a2ui` and dropped
the client's `render_a2ui`. Both wiring paths passed the tool choice to the model
call unchanged, and both defaulted to no tool choice at all when nothing was
given. Exhausting the attempts produced an `a2ui_recovery_exhausted` result
carrying `error`, `code`, and `attempts` and no operations, which is what the
README claims about a failed generation.

---

## Validation, A2UI docs refresh

- `./scripts/format.sh` and `./scripts/validate.sh` clean.
- `check_cookbook_pattern.py --base-dir cookbook/05_agent_os/16_agui`: 11 files,
  0 violations.

---

## A2UI docs re-verification, 2026-09-08

A second review round found claims in `README.md` that the module no longer
supports. Every claim in the README's A2UI section, and every claim in the two
A2UI example files, was re-read against the current
`agno/os/interfaces/agui/a2ui.py`, `a2ui_stream.py`, `router.py`, `handlers.py`,
`agui.py`, the `Agent.tools` signature, the OpenAI Responses, Gemini, and
Anthropic model modules, and the installed `ag-ui-a2ui-toolkit 0.0.4`. No code
was changed.

**Status:** PASS

**Test mode:** SOURCE AND TEST SUITE. No server was booted for this pass; the
runs recorded above stand, and the live-model pass the two A2UI files owe is
still owed.

**Corrected:**

- The README claimed a tool the developer wired with `get_a2ui_tools` is never
  injected over. The two tool detectors of the time each read `entity.tools`
  only when it is a list, so a `tools` given as a callable factory was
  invisible to both and a second tool of the same name was injected; a flat
  `{"name": ...}` dict was missed by the name detector for the same reason. The
  README stated which shapes were seen, which were not, and what happened to a
  run against one that was not. Both detectors were later replaced by the
  single `resolve_entity_tools`, which closed those gaps; see the 2026-09-09
  round below.
- The README said the missing-toolkit path logs a warning. `_plan_a2ui_run` in
  `router.py` calls `log_error`, and a unit test pins the emitted level, so the
  README now says error.
- The README's list of Gemini tool-choice strings omitted `"validated"`, which
  `Gemini.get_request_params` maps like `"auto"`, `"none"`, and `"any"`.
- This log cited four commit hashes, three of which are no longer ancestors of
  the branch after a rebase onto a new upstream release. Runs are now identified
  by date, scope, and pinned dependency versions.
- This log reported 281 passing interface tests, which the suite had already
  grown past. Counts now live in each round's own validation block.
- A `FAKE MODEL` label, two missing entry separators, and a `Validation`
  heading at two different levels were brought in line with the rest of the
  file.
- The addition's validation list recorded 27 pre-existing core mypy errors in
  six files outside this integration's diff. `./scripts/validate.sh` now
  reports no issues across 1050 source files, so that note is superseded.

**Re-verified and left standing:** the two-way comparison table; the exact-text
match on the schema context entry, byte-identical to the toolkit's own
`A2UI_SCHEMA_CONTEXT_DESCRIPTION`; the basic-catalog fallback when no catalog is
forwarded and no `default_catalog_id` is pinned; the hands-off path leaving the
client's render tool in place; nesting of render progress inside the generation
call as `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`; three recovery
attempts by default with camelCase `maxAttempts` and a warning on a snake_case
key; the 180-second default render-turn bound; the `a2ui_recovery_exhausted`
envelope carrying `error`, `code`, `attempts`, no operations, and
`subagentErrors` on a provider failure; `OpenAIResponses` accumulating tool
arguments internally and publishing them only at `response.output_item.done`,
which is why `a2ui_generated_ui.py` uses `OpenAIChat`; Gemini rejecting the
forced-function object and Anthropic accepting `tool_choice` and never
forwarding it; and `a2ui_fixed_schema.py`'s authored tree, which the toolkit's
own validator accepts against the data model the tool supplies.

---

## Validation, A2UI docs re-verification

- `libs/agno/tests/unit/os/interfaces/` and `libs/agno/tests/unit/app/` were
  green at the time, with the strict expected-failures then in place. For the
  counts as they stand, see the 2026-09-09 round below.
- `./scripts/format.sh` and `./scripts/validate.sh` clean.
- `check_cookbook_pattern.py --base-dir cookbook/05_agent_os/16_agui`: 11 files,
  0 violations.

---

## A2UI docs re-verification, 2026-09-09

A third review round found the README describing tool-shape blind spots that the
tool detectors no longer have, and this log describing expected-failures the
suite no longer contains. `resolve_entity_tools` in
`agno/os/interfaces/agui/a2ui_stream.py` and `prepare_a2ui_run` in
`agno/os/interfaces/agui/a2ui.py` were read as they stand on this branch, along
with the tests that parametrize every tool shape in
`libs/agno/tests/unit/os/interfaces/test_agui_a2ui_injection.py`.

**Status:** PASS

**Test mode:** SOURCE AND TEST SUITE. No server was booted for this pass; the
runs recorded above stand, and the live-model pass the two A2UI files owe is
still owed. Both A2UI example files were imported and their apps built.

**Corrected:**

- The README said a generation tool inside a `Toolkit` stops injection without
  being recognized as generating, so its surface arrives whole. One walk of the
  tools list now answers both questions from the same reading, and a `Toolkit`
  is walked for its functions, so such a run is recognized and does get the
  render channel.
- The README said a flat `{"name": ...}` tool dict carries no name to read.
  `_tool_dict_name` reads a name from the flat spelling as well as the nested
  one, so that shape now holds the generation tool's name against injection.
- The README said a run against a `tools` callable, or against a flat dict, has
  a second tool of the same name injected over it. An unreadable tools list is
  now reported as an explicit third answer rather than as absence, and
  injection is declined with a warning saying why. The render channel is still
  prepared for such a run, so a generation tool the callable builds paints as
  it streams.
- This log recorded 395 passed and 18 xfailed and inventoried six groups of
  strict expected-failure. There are none left: 487 passed, no expected
  failures, and the inventory was removed rather than updated, since the thing
  it described no longer exists.
- This log named `entity_generates_a2ui` and `entity_tool_names`. Both are gone,
  replaced by the single `resolve_entity_tools`.
- Comments in `router.py` and `handlers.py` said a retried render attempt reuses
  the tool-call id its rejected predecessor was closed under. `A2UIRenderAttempt`
  mints a wire id per attempt precisely so that cannot happen, and its own
  docstring says a reused id would leave the healed surface unpainted. Both
  comments now describe what the branch actually guards, a start arriving for an
  id already closed, and the test docstring that made the same claim was
  corrected with them.
- A test comment said the README describes the missing-toolkit path as logging a
  warning. The README was corrected to say error in the round above, so the
  comment now records the two as pinned to each other.
- `a2ui_fixed_schema.py` gave its agent a `db` and invited a multi-turn
  conversation without `add_history_to_context`, so every follow-up arrived with
  no memory of the card just shown and the stored history was never read. The
  option is set now, with the reason in the file, as `a2ui_generated_ui.py`
  already had it.
- `a2ui_generated_ui.py`'s use of `OpenAIChat` against the cookbook rule was
  explained in its module docstring only. The exemption is now recorded at the
  import and the model call, which is where a sweep for the name lands.

**Re-verified and left standing:** injection being off unless asked for, with a
client's `injectA2UITool: false` overriding a backend `inject_a2ui_tool`; the
catalog moving into run state only on a run that is injected into; the exact
text of the schema context entry, still byte-identical to the toolkit's own
`A2UI_SCHEMA_CONTEXT_DESCRIPTION`; the declined run keeping the client's render
tool and the pause a call to it costs; `log_error` on the missing-toolkit path;
`DEFAULT_RENDER_TOOL_CHOICE` being `None` with `OPENAI_RENDER_TOOL_CHOICE`
exported for hosts that want forcing; the 180-second
`DEFAULT_RENDER_SUBAGENT_TIMEOUT`; three recovery attempts with camelCase
`maxAttempts`; and the `a2ui_recovery_exhausted` envelope.

**Not covered by any test at this version:** `resolve_entity_tools` reads the
entity's own `tools` only, so a generation tool held by a team member is not
seen when the interface is given the team. The README claims nothing either way
about members.

---

## Validation, A2UI docs re-verification 2026-09-09

- `libs/agno/tests/unit/os/interfaces/` and `libs/agno/tests/unit/app/`:
  487 passed, no expected failures.
- `./scripts/format.sh` and `./scripts/validate.sh` clean.
- `check_cookbook_pattern.py --base-dir cookbook/05_agent_os/16_agui`: 11 files,
  0 violations.
- Both A2UI example files imported and built their `app`.
