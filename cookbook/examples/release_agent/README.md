# Release Agent

Publish a release-note writer as an MCP tool.
A small runnable companion to [Release Agent](https://docs.agno.com/use-cases/agents-as-mcp).

## Run locally

From the repository root (or start inside the downloaded example directory):

```bash
cd cookbook/examples/release_agent
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python release_mcp.py
```

In a second terminal, activate the environment and run `python demo.py`. It uses
a real MCP client to call `write_release_notes` with three product changes.
Expect release notes covering filtered CSV exports, renamed saved reports, and
fixed duplicate notifications, without invented dates or availability claims.

For Claude Code, run:

```bash
claude mcp add --transport http release-agent http://localhost:7777/mcp
```

The local MCP endpoint is `http://localhost:7777/mcp`. The agent's continue and
cancel tools are also exposed to support paused runs. SQLite stores conversations
in `release-agent.db`; continuity requires supplying the same session and user.
This unauthenticated service binds to loopback. Configure authentication and
identity mapping before making it reachable by remote clients.

## Build further

Read the linked use-case guide for the next step. Choose a
[deployment template](https://docs.agno.com/deploy/introduction) when you need a
fully deployable application. All examples here use OpenAI's `gpt-5.6`; model
responses vary. See [TEST_LOG.md](TEST_LOG.md) for what has been validated.
