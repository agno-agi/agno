# Test Log: 15_a2a

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`. `basic.py`, `client.py`,
`agent_card.py` and `team.py` were re-run on 2026-10-10 against the A2A v1.0
interface (a2a-sdk 1.2.2). `external_agent.py` was added and run on 2026-10-10.
`basic.py`, `client.py`, `agent_card.py`, `team.py`, `external_agent.py` and
the three `multi_agent/` servers were re-run on 2026-10-30 against the working
tree on top of `bff768e181` (a2a-sdk 1.2.2, openai-codex 0.163.0).

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the SQLite-backed A2A Agent server on port 7779,
checked its standard AgentOS surface and Agent card, then kept it running for
the first-party client tests.

**Result:** `GET /health` returned `ok`; `GET /config` returned OS
`a2a-basic-os`, Agent `a2a-assistant`, and interface route `/a2a`. The Agent
card returned name `A2A Assistant`, version `1.0.0`, and A2A endpoint
`http://127.0.0.1:7779/a2a/agents/a2a-assistant` for both A2A v1.0 and v0.3.

---

### client.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran non-streaming, multi-turn, streaming, and unavailable
server paths against the live `basic.py` server.

**Result:** Initial task `32b1e24d-1313-4b2a-a34f-d7f6cf786622` returned
context `90ae17d6-1253-417e-9963-df2ef3d5f191`. The follow-up reused that exact
context and returned `cedar-42`. Streaming produced `task`, `working`,
`content`, `artifact`, and final `completed` events. A dynamically selected
unused local port raised and was caught as `RemoteServerUnavailableError`.

---

### agent_card.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Read the live Agent card with the synchronous
`get_agent_card()` method and asynchronous `aget_agent_card()` method.

**Result:** Both methods returned the same name `A2A Assistant`, description,
version `1.0.0`, entity-scoped A2A endpoint, protocol versions `['1.0', '0.3']`,
and skills `['a2a-assistant']`. The synchronous method was called directly and
only the asynchronous method was awaited.

---

### team.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the Team server on port 7779, inspected health,
configuration, and discovery, then ran the checked-in `--demo` client.

**Result:** `GET /config` returned OS `a2a-team-os`, Team `research-team`, and
interface route `/a2a`. The Team card (version `1.0.0`) resolved under
`/a2a/teams`. Task `31ff5e97-4e98-4f23-948f-121d252ae9b7` completed and
returned two concise reasons to keep API examples small.

---

### external_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the external Agent server on port 7779 with
`sandbox_mode="read-only"`, inspected configuration, then ran the checked-in
`--demo` client.

**Result:** `GET /config` returned OS `a2a-external-os`, Agent
`codex-assistant`, and interface route `/a2a`. The Agent card endpoint resolved
under `/a2a/agents`. Task `ae45cb29-4db4-4c66-8326-c3f0f68f2275` completed and
returned a one-sentence description of a list comprehension. `aget_task` read
the stored task back with status `completed`. The server emitted no
deprecation warning.

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
advertised the correct port-7782 entity endpoint. On 2026-10-30 the card
returned version `1.0.0`, and the planner's call completed and reported the
expected OpenWeather `401 Unauthorized`. A valid `OPENWEATHER_API_KEY` is
required to validate real weather data.

---

### multi_agent/airbnb_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started AgentOS with the OpenBNB MCP subprocess, inspected
health, configuration, and discovery, then called the Agent over A2A.

**Result:** On 2026-10-30, Node `v22.22.0` launched the OpenBNB MCP server.
`GET /config` returned OS `a2a-airbnb-os` and Agent `airbnb-agent`; the card
returned version `1.0.0`. The planner's call completed after invoking
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

**Result:** All three health, config, and Agent-card routes responded; each
card returned version `1.0.0`. Planner task
`83aec3cc-ecee-42c1-9ce3-5e13d66719f2` called the weather Agent and the Airbnb
Agent through the official async `A2AClient`, consumed each
`TaskResult.content`, and returned a combined two-night Paris itinerary. The final
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
