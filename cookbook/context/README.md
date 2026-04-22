# Context Providers

Context Providers expose any external source — the web, a filesystem,
Slack, Google Drive — to an agent as a first-class, queryable context.

Every provider subclasses `agno.context.ContextProvider` and implements:

- `query(question) / aquery(question) -> Answer` — natural-language access
- `status() / astatus() -> Status` — is the source reachable?

Each provider exposes its tools via `provider.get_tools()`, which the
calling agent wires into its own `tools=[...]`.

## Modes

`mode` controls how a provider surfaces itself:

| Mode | Exposure |
|---|---|
| `default` | The provider's recommended exposure (each subclass decides). |
| `tools` | The provider's underlying tools directly. |
| `agent` | One `query_<id>` tool wrapping a sub-agent. |

## Examples

| File | Provider | Notes |
|---|---|---|
| `web_parallel.py` | `WebContextProvider` + `ParallelBackend` | Requires `PARALLEL_API_KEY` |
| `web_exa.py` | `WebContextProvider` + `ExaBackend` | Requires `EXA_API_KEY` |
| `web_exa_mcp.py` | `WebContextProvider` + `ExaMCPBackend` | Keyless — uses Exa's public MCP |
| `filesystem.py` | `FilesystemContextProvider` | Read-only, rooted at a local dir |
| `slack.py` | `SlackContextProvider` | Read-only, requires `SLACK_BOT_TOKEN` |
| `gdrive.py` | `GDriveContextProvider` | Service-account auth, read-only |

## Run

```bash
.venvs/demo/bin/python cookbook/context/<file>.py
```
