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
The mocked cookbook smoke test also passes with `pprint_run_response(response)`
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

**Description:** Execute `Agent.arun` with an asynchronous SDK client.

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
