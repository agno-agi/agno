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
| `SlackContextProvider` | A Slack workspace (read-only) | `query_<id>` (search / history / threads / users sub-agent) |
| `GDriveContextProvider` | Google Drive via service account | `query_<id>` (list / search / read sub-agent; all-drives aware) |

## Cookbooks

| File | What it shows |
|------|---------------|
| `00_filesystem.py` | Browse local files via `FilesystemContextProvider` |
| `01_web_exa.py` | Web research via `WebContextProvider(backend=ExaBackend())` |
| `02_database_read_write.py` | Read + write a SQLite DB; end-to-end round trip |
| `03_slack.py` | Read-only Slack workspace search + channel history |
| `04_google_drive.py` | Google Drive via a service account; reads a shared Doc |
| `05_multi_provider.py` | Three providers on one agent; names compose cleanly |
| `06_custom_provider.py` | Subclass `ContextProvider` for your own source |

## Run

```bash
# Self-contained (no external service)
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/context/00_filesystem.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/context/02_database_read_write.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/context/06_custom_provider.py

# Needs Exa
OPENAI_API_KEY=... EXA_API_KEY=... .venvs/demo/bin/python cookbook/context/01_web_exa.py

# Needs Slack bot token (xoxb-...)
OPENAI_API_KEY=... SLACK_BOT_TOKEN=xoxb-... .venvs/demo/bin/python cookbook/context/03_slack.py

# Needs a Google service-account JSON with at least one folder shared to its email
OPENAI_API_KEY=... GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json \
    .venvs/demo/bin/python cookbook/context/04_google_drive.py

# Needs OpenAI + Exa
OPENAI_API_KEY=... EXA_API_KEY=... .venvs/demo/bin/python cookbook/context/05_multi_provider.py
```
