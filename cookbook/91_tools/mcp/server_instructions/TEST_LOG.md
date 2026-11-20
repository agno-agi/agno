# Test Log

### client.py

**Status:** PASS

**Description:** Spawns `server.py` over stdio through `MCPTools` and checks that the
server's handshake `instructions` are adopted as toolkit instructions with
`add_instructions=True`, that `load_server_instructions=False` leaves them unset, and
that explicit `instructions=` on the toolkit are not overwritten. The agent turns need
`OPENAI_API_KEY`; see Result for what was and was not run.

**Result:** With the `.venv` on `PATH`, `MCPTools("python .../server.py")` started the server over stdio, discovered `lookup_station` and `get_forecast`, and loaded the server's instructions verbatim with `add_instructions=True`. `load_server_instructions=False` left `instructions=None`, and `instructions="Mine."` on the toolkit stayed `"Mine."`. The two `aprint_response` turns were not executed in this workspace because `OPENAI_API_KEY` was not set.

---
