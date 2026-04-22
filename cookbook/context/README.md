# Context Providers

`agno.context` exposes a uniform API for plugging an external source
into an agent as a natural-language tool.

A `ContextProvider` owns two things:

1. `query(question)` / `aquery(question)` — natural-language access; returns an `Answer`.
2. `get_tools()` — the tool surface the calling agent sees. By default,
   this is a single `query_<id>` tool (plus `update_<id>` for writable
   providers) that routes through a scoped sub-agent.

Providers ship in this package:

| Provider | Source | Tools |
|----------|--------|-------|
| `FilesystemContextProvider` | Local directory tree | `query_<id>` (read-only `FileTools` sub-agent) |
| `WebContextProvider` + `ExaBackend` | The open web via Exa | `query_<id>` (search + fetch sub-agent) |
| `DatabaseContextProvider` | Any SQL database (SQLAlchemy) | `query_<id>`, `update_<id>` (separate read/write sub-agents) |
| `MCPContextProvider` | One MCP server | `query_<id>` (sub-agent over the server's tools) |

## Cookbooks

| File | What it shows |
|------|---------------|
| `00_minimal_provider.py` | Subclass `ContextProvider` in-place (in-memory quotes) |
| `01_filesystem.py` | Browse local files via `FilesystemContextProvider` |
| `02_web_exa.py` | Web research via `WebContextProvider(backend=ExaBackend())` |
| `03_database_read_write.py` | Read + write a SQLite DB; end-to-end round trip |
| `04_mcp_server.py` | Connect to Exa's keyless MCP server; lazy connect + `aclose()` |
| `05_multi_provider.py` | Three providers on one agent; names compose cleanly |

## Run

```bash
# Minimal / filesystem / DB / multi
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/context/00_minimal_provider.py

# Web / multi (also needs Exa)
OPENAI_API_KEY=... EXA_API_KEY=... .venvs/demo/bin/python cookbook/context/02_web_exa.py

# MCP (keyless, no Exa key required)
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/context/04_mcp_server.py
```
