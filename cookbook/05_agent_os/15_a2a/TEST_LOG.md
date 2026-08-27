# Test Log: 15_a2a

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the SQLite-backed A2A Agent server on port 7779,
checked its standard AgentOS surface and Agent card, then kept it running for
the first-party client tests.

**Result:** `GET /health` returned `ok`; `GET /config` returned OS
`a2a-basic-os`, Agent `a2a-assistant`, and interface route `/a2a`. The Agent
card returned name `A2A Assistant`, version `1.0.0`, and stream endpoint
`http://127.0.0.1:7779/a2a/agents/a2a-assistant/v1/message:stream`.

---

### client.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran non-streaming, multi-turn, streaming, and unavailable
server paths against the live `basic.py` server.

**Result:** Initial task `b17568ab-ee9f-4ae3-bf59-1764310e3274` returned
context `e9ed46f7-d205-478b-9c06-49f51751c84b`. The follow-up reused that exact
context and returned `cedar-42`. Streaming produced `working`, `content`,
`completed`, and final `task` events. A dynamically selected unused local port
raised and was caught as `RemoteServerUnavailableError`.

---

### agent_card.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Read the live Agent card with the synchronous
`get_agent_card()` method and asynchronous `aget_agent_card()` method.

**Result:** Both methods returned the same name `A2A Assistant`, description,
version `1.0.0`, and entity-scoped stream endpoint. The synchronous method was
called directly and only the asynchronous method was awaited.

---

### team.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the Team server on port 7779, inspected health,
configuration, and discovery, then ran the checked-in `--demo` client.

**Result:** `GET /config` returned OS `a2a-team-os`, Team `research-team`, and
interface route `/a2a`. The Team card endpoint resolved under `/a2a/teams`.
Task `021632de-761c-42e5-91cd-5d299482860a` completed and returned two concise
reasons to keep API examples small.

---

### multi_agent/weather_agent.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** The environment had no valid `OPENWEATHER_API_KEY`. Constructed
and booted the server with a non-secret placeholder to validate AgentOS and
A2A wiring, then made one live A2A request to exercise explicit provider-error
handling.

**Result:** `GET /health` returned `ok`; `GET /config` returned OS
`a2a-weather-os`, Agent `weather-agent`, and interface route `/a2a`. The card
advertised the correct port-7782 entity endpoint. Task
`39887879-5439-4492-851c-e3e456d1b501` completed and clearly reported the
expected OpenWeather `401 Unauthorized`. A valid `OPENWEATHER_API_KEY` is
required to validate real weather data.

---

### multi_agent/airbnb_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS with the OpenBNB MCP subprocess, inspected
health, configuration, and discovery, then called the Agent over A2A.

**Result:** Node `v23.11.0` launched OpenBNB MCP server `0.1.4`; AgentOS
registered `airbnb_search` and `airbnb_listing_details`. `GET /config` returned
OS `a2a-airbnb-os`, Agent `airbnb-agent`, and interface route `/a2a`. Task
`e4e57fd5-ecb3-47ff-afed-0f5669dede90` completed after invoking
`airbnb_search`. The external MCP server reported that Airbnb's current page
could not be parsed, and the Agent surfaced that limitation plus a direct
search URL instead of inventing listings.

---

### multi_agent/trip_planning_a2a_client.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the weather server on 7782, Airbnb server on 7783, and
trip planner on 7779, then invoked the checked-in `--demo` over the planner's
A2A route.

**Result:** All three health, config, and Agent-card routes responded. Planner
task `30073d75-269f-4a56-a4fe-9195a488c75b` called the weather Agent first and
the Airbnb Agent second through the official async `A2AClient`, consumed each
`TaskResult.content`, and returned a combined Paris itinerary. The final
response preserved the honest downstream limitations: invalid test weather
credentials and the OpenBNB parser's current Airbnb-page failure.

---

## Validation

- All live servers shut down cleanly; ports 7779, 7782, and 7783 had no
  remaining listeners or MCP subprocesses.
- Recursive pattern validation checked exactly 7 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Python compilation, exact inventory, retained Phase 5 sources, stale-model,
  route-prefix, deprecated-surface, Unicode/emoji, non-PASS status, and
  `git diff --check` gates passed.
