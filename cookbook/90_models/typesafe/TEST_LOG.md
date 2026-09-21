# Jev integration test log

Date: 2026-09-20. Environment: Windows, Python 3.12.11, TypeSafe SDK 0.7.0.
Provider requests in these checks are mocked. No live TypeSafe or generative
provider calls were made; classification quality, latency and threshold
calibration remain for private-branch testing.

### questions.py

**Status:** PASS (mocked)

**Description:** Execute the cookbook with official SDK-shaped decision responses.

**Result:** SDK questions compile and JSON decision content is returned.

### structured_output.py

**Status:** PASS (mocked)

**Description:** Validate typed input and an annotated Pydantic output.

**Result:** Choice labels, thresholded booleans and fractional scores retain
their declared types; raw probabilities remain in provider metadata.
The mocked cookbook smoke test also passes with `agent.print_response(...)`
for the structured content and Rich `pprint` for provider metadata. Ruff lint
and formatting checks pass for the updated example.

### route_team.py

**Status:** PASS (mocked)

**Description:** Route a request and stream the selected member's response.

**Result:** Exactly one member executes and receives the original input.
The unit suite also exercises async routing and changing member rosters.

### workflow.py

**Status:** PASS (mocked)

**Description:** Execute Jev classification followed by a generative step.

**Result:** The decision passes through the workflow step interface.

### tool_use.py

**Status:** PASS (mocked)

**Description:** Select finite tool arguments and execute one function.

**Result:** The tool result is returned without a synthesis call. Separate
unit tests cover sync/async, streaming, no-tool, forced selection, optional
arguments, confirmation and external-execution resumes.

### llm_tool.py

**Status:** PASS (mocked)

**Description:** Load and run both generative-agent configurations.

**Result:** Both examples execute with mocked generative responses. Separate
unit tests exercise actual Jev tool invocation through the Agent executor and
the explicit dynamic-question opt-in.

### guardrails.py

**Status:** PASS (mocked)

**Description:** Execute an input check and output grounding check with evidence.

**Result:** Allowed content passes. Separate unit tests cover rejection,
SDK failures, background hooks, output suppression, and refusal to stream
before output validation.

### async_decisions.py

**Status:** PASS (mocked)

**Description:** Execute `Agent.aprint_response` with an asynchronous SDK client.

**Result:** The asynchronous path returns the expected decision.

### SDK transport and framework regression checks

The unit suite uses both SDK response objects and real `TypeSafeClient` /
`AsyncTypeSafeClient` instances with `httpx2.MockTransport`. This exercises
request encoding, response decoding, request IDs and usage without network
calls. Other checks cover serialization, caches, input/schema rejection,
probability metadata, routing thresholds and fallbacks.

Windows sandboxed pytest could not access its own temporary directories.
The regression suite was rerun with normal temporary-directory permissions.
See the test command in the integration README for reproducing it.

Final adjacent regression run: **464 passed, 16 skipped**. Included the 64 Jev
tests plus provider resolution, Agent/Team hooks and run options, callable Team
members, model inheritance and Team modes. Skips were optional provider SDKs.

Repository checks:

- Ruff check: PASS for `libs/agno`, `libs/agnoctl`, and `cookbook`.
- Ruff format check: PASS, 4,913 files already formatted across all four targets.
- Cookbook pattern check: PASS, 13 quickstart examples, zero violations.
- Focused mypy for Jev and all modified framework modules: PASS, 16 source files.
- Agnoctl mypy: PASS, 21 source files.
- Full Agno mypy: FAIL, 66 errors in 14 untouched files. Diagnostics involve
  Google SDK compatibility, missing regex stubs, Redis typing, MCP SDK signatures,
  Groq audio methods, Discord helpers, in-memory DB typing and AWS Claude.
  No errors were reported in the Jev modules or modified integration points.

Validation used the equivalent script commands through `.venv/Scripts/python.exe`
on Windows. Full diagnostics are retained locally in `.context/jev-mypy.log`.

## Port from integrate-jev — 2026-09-21

**Status:** PASS (mocked regression tests)

**Description:** Added named guardrail checks, shorthand questions, per-check thresholds, typed `ask_jev`, and toolkit guidance. Preserved existing fixed-tool configuration and guardrail failure behavior. Removed broadcast judging, its example, and the change to member streaming; Jev Team leaders support routing only.

**Result:** 507 tests passed, 16 optional-provider tests skipped, including all 107 Jev tests and 11 cookbook smoke cases. Coverage includes rejection of broadcast leaders before execution, sync/async tool calls, local question validation, batched input/output checks, exact thresholds, guardrail error details, routing, hook propagation, Team configuration, provider resolution, and caching.

The examples previously named `route_team.py`, `workflow.py`, `llm_tool.py`, and `guardrails.py` were replaced or moved into their feature folders. The README links their current locations. Model-only examples remain here; all Jev examples use pretty printers, with `team.print_response` in the router example.

The port passed focused mypy before removal of broadcast judging; the model and Team tool module are now restored to their pre-port implementations. All 11 remaining Jev examples use pretty printers. Updated README links resolve.

No live API calls were made. Quality, latency, and threshold tuning remain for private-branch testing.

### CI type checking without the optional SDK

**Status:** PASS (targeted reproduction)

**Description:** Run mypy with the repository configuration and `--no-site-packages` against the SDK imports used by the integration. This reproduces the missing `typesafe_sdk` dependency in the CI development environment.

**Result:** The import failed before adding `typesafe_sdk.*` to the existing optional-dependency overrides and passed afterward. An unrelated missing-module control still fails, confirming missing imports are not ignored globally. Runtime SDK dependency handling is unchanged.

Focused mypy also passes for the seven Jev model, guardrail, and toolkit source files.

## Additional examples and response panels — 2026-09-21

### basic.py

**Status:** PASS (mocked)

**Description:** Classify support department, urgency, and fractional frustration.

**Result:** Executes through `agent.print_response`; the saved run supplies provider metadata and metrics.

### async_basic.py

**Status:** PASS (mocked)

**Description:** Classify three reviews concurrently through `agent.aprint_response`, sharing one async client with separate sessions.

**Result:** Three requests overlap and each calls the SDK once. Saved outputs retain nested topic flags and recommendation intent. Separate buffered consoles keep response panels together; saved dictionaries are validated back into the review schema for diagnostics.

### raw_questions.py

**Status:** PASS (mocked)

**Description:** Evaluate refund intent, policy eligibility, next action, and effort using raw question dictionaries.

**Result:** The response panel renders, and application code applies explicit probability thresholds to the saved decision values.

### tools_use_with_fallback.py

**Status:** PASS (mocked)

**Description:** Simulate lights, thermostat, and multi-door commands, with an explicit generative fallback for no-tool decisions.

**Result:** Parameterized tests verify selected tools, arguments, omitted defaults, and original-input forwarding to the fallback. SDK failures do not invoke fallback. The original support-queue `tool_use.py` remains and passes its own smoke test.

All eight model examples use `print_response` or `aprint_response`; Rich `pprint` handles diagnostics. Final focused suite: **117 passed**, including 15 cookbook smoke cases. Ruff lint and formatting checks pass for the model cookbooks and Jev tests. These checks use mocked providers, not live API calls.

## Restored minimal model examples — 2026-09-21

### route_team.py

**Status:** PASS (mocked)

**Description:** Restore the two-member billing/technical team with Jev as the routing leader and explicit generative member models.

**Result:** Both sample requests execute through `team.print_response(..., stream=True)`. The expanded support-router example remains in the teams folder.

### workflow.py

**Status:** PASS (mocked)

**Description:** Restore the linear Jev classification followed by a generative explanation step.

**Result:** The workflow executes through `workflow.print_response`. The conditional Router example remains in the workflows folder. README guidance explains why classification and routing use Jev while prose generation uses a generative model.

Validation: **119 tests passed**, including all 17 Jev cookbook smoke cases. Ruff lint and formatting pass for the model examples and Jev unit tests. No live API calls or cost measurements were made.

### basic.py and questions.py — department examples

**Status:** PASS (mocked)

**Description:** Run one sample input per department option: billing, technical, and sales in `basic.py`; billing and technical in `questions.py`. Both reuse their agent and render each request through `agent.print_response`.

**Result:** All four smoke cases selected by `cookbook_smoke and (basic or questions)` pass, including both updated files. Lint and formatting pass. These mocked checks verify execution; live classification quality remains untested.

### agent_os.py

**Status:** PASS (mocked API checks)

**Description:** Serve a typed Jev ticket classifier and a Jev-led support routing team through AgentOS. The example uses SQLite for local sessions; tests substitute an in-memory database and mocked providers.

**Result:** Four parameterized API checks pass: billing and technical requests, each with JSON and streamed responses. `/config` and `/openapi.json` load successfully. Each request makes one async Jev call; routing invokes only the selected specialist with the original input. The example uses `TeamMode.route` so the AgentOS configuration can serialize its mode. Ruff lint and formatting pass. No live API calls were made.

### accuracy_eval.py — 2026-09-21

**Status:** PASS (mocked)

**Description:** Display a generated answer through `agent.print_response`, then
retrieve the same completed run and compare it against a reference with Jev.

**Result:** Exactly one generation call and one scoring call occur. The score is
displayed with Rich `pprint`. Full accuracy examples live in
`cookbook/09_evals/accuracy/`; their test log records all four example smoke checks.

All **52** new scorer tests pass. The combined scorer, eval, and Jev regression
run reports **406 passed, 1 failed**: an unchanged MCP cleanup test cannot import
`MCPError` from the installed package, which exposes `McpError`. The failure
reproduces in isolation. No existing accuracy or AgentOS eval APIs were changed.
Ruff lint, formatting, and whitespace checks pass. The focused mypy check passes
for the new scorer with the repository configuration and `--follow-imports=silent`.
Live judgment quality and threshold calibration remain for private-branch testing.
