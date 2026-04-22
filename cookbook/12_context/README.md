# Context Providers

`agno.context` exposes a uniform API for plugging an external source
into an agent as a natural-language tool.

A `ContextProvider` owns two things:

1. `query(question)` / `aquery(question)` — natural-language access; returns an `Answer`.
2. `get_tools()` — the tool surface the calling agent sees. By default,
   this is a single `query_<id>` tool (plus `update_<id>` for writable
   providers) that routes through a scoped sub-agent.

Providers that hold async resources (MCP sessions, watched inboxes,
etc.) also implement `asetup()` / `aclose()`. Callers should bracket
their use with these so the resource's lifetime is owned by a single
task — typically wired into the application lifespan.

Providers ship in this package:

| Provider | Source | Tools |
|----------|--------|-------|
| `FilesystemContextProvider` | Local directory tree | `query_<id>` (read-only `FileTools` sub-agent) |
| `WebContextProvider` + `ExaMCPBackend` | Web via Exa's public MCP server (keyless / keyed) | `query_<id>` (search + fetch sub-agent) |
| `WebContextProvider` + `ExaBackend` | Web via Exa's direct SDK | `query_<id>` (search + fetch sub-agent) |
| `WebContextProvider` + `ParallelBackend` | Web via Parallel's beta API | `query_<id>` (search + fetch sub-agent) |
| `DatabaseContextProvider` | Any SQL database (SQLAlchemy) | `query_<id>`, `update_<id>` (separate read/write sub-agents) |
| `SlackContextProvider` | A Slack workspace (read-only) | `query_<id>` (search / history / threads / users sub-agent) |
| `MCPContextProvider` | One MCP server | `query_<id>` (sub-agent over the server's tools) or flat tools in `mode=tools` |
| `GDriveContextProvider` | Google Drive via service account | `query_<id>` (list / search / read sub-agent; all-drives aware) |

## Cookbooks

| File | What it shows |
|------|---------------|
| `00_filesystem.py` | Browse local files via `FilesystemContextProvider` |
| `01_web_exa_mcp.py` | Web research via Exa's keyless public MCP endpoint |
| `02_web_exa.py` | Web research via Exa's direct SDK (needs `EXA_API_KEY`) |
| `03_web_parallel.py` | Web research via Parallel's beta API |
| `04_database_read_write.py` | Read + write a SQLite DB; end-to-end round trip |
| `05_slack.py` | Read-only Slack workspace search + channel lookup |
| `06_mcp_server.py` | Wrap an MCP server; explicit `asetup` / `aclose` lifecycle |
| `07_google_drive.py` | Google Drive via a service account; reads a shared Doc |
| `08_multi_provider.py` | Three providers on one agent; names compose cleanly |
| `09_custom_provider.py` | Subclass `ContextProvider` for your own source |

## Run

```bash
# Self-contained (no external service)
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/00_filesystem.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/04_database_read_write.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/09_custom_provider.py

# Keyless Exa MCP — no signup required
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/01_web_exa_mcp.py

# Exa SDK (keyed) — higher throughput
OPENAI_API_KEY=... EXA_API_KEY=... .venvs/demo/bin/python cookbook/12_context/02_web_exa.py

# Parallel SDK
OPENAI_API_KEY=... PARALLEL_API_KEY=... .venvs/demo/bin/python cookbook/12_context/03_web_parallel.py

# Slack bot token (xoxb-...)
OPENAI_API_KEY=... SLACK_BOT_TOKEN=xoxb-... .venvs/demo/bin/python cookbook/12_context/05_slack.py

# `uvx` on PATH (ships with `uv`) — the MCP time server is downloaded on first run
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/06_mcp_server.py

# Google service-account JSON with at least one folder shared to its email
OPENAI_API_KEY=... GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json \
    .venvs/demo/bin/python cookbook/12_context/07_google_drive.py

# Multi-provider (fs + web + db) — web uses Exa MCP, so no EXA key required
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/08_multi_provider.py
```
