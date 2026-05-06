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
| `WorkspaceContextProvider` | Local project workspace | `query_<id>` (read-only `Workspace` sub-agent with project-aware excludes) |
| `WebContextProvider` + `ExaMCPBackend` | Web via Exa's public MCP server (keyless / keyed) | `query_<id>` (search + fetch sub-agent) |
| `WebContextProvider` + `ExaBackend` | Web via Exa's direct SDK | `query_<id>` (search + fetch sub-agent) |
| `WebContextProvider` + `ParallelBackend` | Web via Parallel's beta API | `query_<id>` (search + fetch sub-agent) |
| `WebContextProvider` + `ParallelMCPBackend` | Web via Parallel's public MCP server (keyless / keyed) | `query_<id>` (search + fetch sub-agent) |
| `DatabaseContextProvider` | Any SQL database (SQLAlchemy) | `query_<id>`, `update_<id>` (separate read/write sub-agents) |
| `SlackContextProvider` | A Slack workspace | `query_<id>`, `update_<id>` (separate read/write sub-agents; writer only gets `send_message` + the lookup tools it needs) |
| `MCPContextProvider` | One MCP server | `query_<id>` (sub-agent over the server's tools) or flat tools in `mode=tools` |
| `GDriveContextProvider` | Google Drive via service account | `query_<id>` (list / search / read sub-agent; all-drives aware) |
| `WikiContextProvider` + `FileSystemBackend` | A directory of markdown files | `query_<id>`, `update_<id>` (separate read/write sub-agents over `Workspace` tools) |
| `WikiContextProvider` + `GitBackend` | A clone of a git repo (PAT auth) | `query_<id>`, `update_<id>`; writes auto-commit, rebase, and push |
| `WikiContextProvider` + `web=ContextBackend` | Wiki + web ingestion (e.g. `ExaMCPBackend`) | Write sub-agent gains web search/fetch so `update_<id>("add this paper")` fetches and digests in one hop |

All read+write providers (`WikiContextProvider`, `DatabaseContextProvider`, `SlackContextProvider`) accept `read=True, write=True` flags. Set `write=False` for a read-only surface (e.g. a code-managed voice wiki, an analytics-only DB), or `read=False` for a write-only sink. Both `False` raises.

## Cookbooks

| File | What it shows |
|------|---------------|
| `00_filesystem.py` | Browse local files via `FilesystemContextProvider` |
| `01_web_exa.py` | Web research via Exa's direct SDK (needs `EXA_API_KEY`) |
| `02_web_exa_mcp.py` | Web research via Exa's keyless public MCP endpoint |
| `03_web_parallel.py` | Web research via Parallel's beta API |
| `04_database_read_write.py` | Read + write a SQLite DB; end-to-end round trip |
| `05_slack.py` | Slack workspace: read channels (always) + optional post via `SLACK_WRITE_CHANNEL` |
| `06_mcp_server.py` | Wrap an MCP server; explicit `asetup` / `aclose` lifecycle |
| `07_google_drive.py` | Google Drive via a service account; reads a shared Doc |
| `08_multi_provider.py` | Three providers on one agent; names compose cleanly |
| `09_web_plus_slack.py` | Compositional: Slack topics feed per-topic web searches |
| `10_custom_provider.py` | Subclass `ContextProvider` for your own source |
| `11_web_parallel_mcp.py` | Web research via Parallel's public MCP endpoint (keyless; `PARALLEL_API_KEY` raises the ceiling) |
| `12_engineering_briefing.py` | Slack topics + codebase workspace + Parallel web into an engineering-sync briefing |
| `13_workspace.py` | Browse a repository root via `WorkspaceContextProvider` without virtualenv / scratch noise |
| `14_wiki_filesystem.py` | Read + write a local markdown wiki via `WikiContextProvider(backend=FileSystemBackend(...))` |
| `15_wiki_git.py` | Same provider against a real git remote; auto-commits and pushes (env-gated on `WIKI_REPO_URL` / `WIKI_GITHUB_TOKEN`) |
| `16_wiki_with_web.py` | Wiki + Exa MCP web backend; "add this paper" fetches the URL, digests it, and files it in one update call |
| `17_wiki_dual.py` | Two `WikiContextProvider` instances on one agent — `company_knowledge` (full) + `company_voice` (`write=False`) |

## Run

```bash
# Self-contained (no external service)
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/00_filesystem.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/04_database_read_write.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/10_custom_provider.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/13_workspace.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/14_wiki_filesystem.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/16_wiki_with_web.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/17_wiki_dual.py

# Wiki against a real git repo (PAT auth; pushes commits)
OPENAI_API_KEY=... \
    WIKI_REPO_URL=https://github.com/<owner>/<repo>.git \
    WIKI_GITHUB_TOKEN=ghp_... \
    .venvs/demo/bin/python cookbook/12_context/15_wiki_git.py

# Exa SDK (keyed) — higher throughput
OPENAI_API_KEY=... EXA_API_KEY=... .venvs/demo/bin/python cookbook/12_context/01_web_exa.py

# Keyless Exa MCP — no signup required
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/02_web_exa_mcp.py

# Keyless Parallel MCP — no signup required; set PARALLEL_API_KEY for higher limits
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/11_web_parallel_mcp.py

# Parallel SDK
OPENAI_API_KEY=... PARALLEL_API_KEY=... .venvs/demo/bin/python cookbook/12_context/03_web_parallel.py

# Slack bot token (xoxb-...); set SLACK_WRITE_CHANNEL=#channel to also demo posting
OPENAI_API_KEY=... SLACK_BOT_TOKEN=xoxb-... .venvs/demo/bin/python cookbook/12_context/05_slack.py

# `uvx` on PATH (ships with `uv`) — the MCP time server is downloaded on first run
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/06_mcp_server.py

# Google service-account JSON with at least one folder shared to its email
OPENAI_API_KEY=... GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json \
    .venvs/demo/bin/python cookbook/12_context/07_google_drive.py

# Multi-provider (fs + web + db) — web uses Exa MCP, so no EXA key required
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/12_context/08_multi_provider.py

# Compositional demo (Slack topics -> per-topic Parallel web searches)
OPENAI_API_KEY=... PARALLEL_API_KEY=... SLACK_BOT_TOKEN=xoxb-... \
    .venvs/demo/bin/python cookbook/12_context/09_web_plus_slack.py

# Advanced briefing demo (Slack topics -> codebase workspace -> Parallel web)
OPENAI_API_KEY=... PARALLEL_API_KEY=... SLACK_BOT_TOKEN=xoxb-... \
    .venvs/demo/bin/python cookbook/12_context/12_engineering_briefing.py
```
