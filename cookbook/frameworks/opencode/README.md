# OpenCode

Use [OpenCode](https://opencode.ai) -- an open-source coding agent -- through Agno.

OpenCode runs as a headless HTTP server with first-class sessions and an SSE
event bus. The `OpenCodeAgent` adapter connects to that server, so it can be
used standalone via `.run()` / `.print_response()` or served through AgentOS
on the standard agent routes, next to native Agno agents.

## Setup

Install the OpenCode CLI and start the server in the directory you want the
agent to work on:

```bash
npm install -g opencode-ai

# Configure a model provider (once)
opencode auth login

# Start the headless server
opencode serve --port 4096
```

## Examples

| File | What it shows |
|------|---------------|
| `opencode_basic.py` | Standalone usage with `.print_response()` |
| `opencode_session.py` | Multi-turn conversations with session persistence |
| `opencode_agentos.py` | Serving OpenCode through AgentOS (SSE + REST) |
| `opencode_structured_output.py` | Structured output (Pydantic) and usage metrics |

## Notes

- `model` is specified as `"provider/model"` (e.g. `"anthropic/claude-sonnet-4-5"`).
  When omitted, the server's default model is used.
- Each Agno `session_id` maps to a dedicated OpenCode session, so multi-turn
  context is kept by the OpenCode server itself.
- Tool calls (read, edit, bash, ...) stream back as Agno tool-call events.
- Runs report token usage and cost on `RunOutput.metrics`.
- Pass a Pydantic model (or a raw JSON schema dict) as `output_schema` for
  structured output validated by the OpenCode server.
- In-flight runs can be cancelled via `agent.acancel_run(run_id)` or the
  AgentOS `POST /agents/{id}/runs/{run_id}/cancel` endpoint; cancelled runs
  end with a `RunCancelled` event and `CANCELLED` status.
- If the server is started with `OPENCODE_SERVER_PASSWORD`, pass `password=`
  (and optionally `username=`) to `OpenCodeAgent`.
