# Test Log — Release Agent

Tested September 16, 2026 with Python 3.14.5, published Agno 3.0.8,
OpenAI 3.14.1, FastMCP 4.0.4, and MCP SDK 2.2.0. The standalone requirements
installed in a fresh environment. Live calls used `gpt-5.6` and synthetic changes.

### release_mcp.py and demo.py

**Status:** PASS

**Description:** Start the actual localhost service, initialize a Streamable HTTP
MCP client, and call `write_release_notes` with the three sample changes.

**Result:** The tool returned release notes covering filtered CSV exports, saved
report renaming, and fixed duplicate notifications. The demo completed with no
MCP error. The client uses the MCP 2 API (`streamable_http_client`, two transport
streams, and `is_error`); requirements explicitly select MCP 2.

---

### AgentOS health

**Status:** PASS

**Description:** Start the real application lifespan and request `/health`.

**Result:** Passed with published Agno 3.0.8 and local Agno 3.0.9 source at
`37fc4121e3cf8863a2957b838fbad7c920bffe0f`. The live-model MCP call above used the
published package. No hosted MCP application, authentication setup, or deployment
was tested.
