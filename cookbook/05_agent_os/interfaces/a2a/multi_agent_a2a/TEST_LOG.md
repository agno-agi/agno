# Test Log: interfaces/a2a/multi_agent_a2a

> Library upgraded to `a2a-sdk>=1.0`. Per-cookbook entries below require real
> model API keys and (in some cases) external services to run end-to-end.

### airbnb_agent.py

**Status:** PENDING

**Description:** Specialized Airbnb search agent over A2A (port 7774). Requires
the OpenBNB MCP server.

---

### weather_agent.py

**Status:** PENDING

**Description:** Specialized weather forecast agent over A2A (port 7770).
Requires `OPENWEATHER_API_KEY`.

---

### trip_planning_a2a_client.py

**Status:** PENDING

**Description:** Trip Planner orchestrator that calls the airbnb and weather
agents via the official `a2a.client` API. Rewritten from the previous
hand-rolled `requests`+JSON-RPC version. Requires airbnb_agent.py and
weather_agent.py running locally first.

---

### streaming_client_demo.py

**Status:** PENDING

**Description:** Standalone `a2a-sdk` client that connects to the weather agent
and iterates over a streaming `message/stream` response, printing each event.
Verifies Agno's streaming interface against the v1 spec. Requires weather_agent.py
running.

---

### agent_card_demo.py

**Status:** PENDING

**Description:** Fetches and pretty-prints the v1 AgentCard from a running
Agno server using `A2ACardResolver`. Defaults to the weather agent; accepts a
base URL as an argument.

---
