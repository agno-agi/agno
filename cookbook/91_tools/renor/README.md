# Renor MCP Memory

Long-term memory for an Agno agent through the [Renor](https://github.com/renorai/renor-engine)
MCP server.

Renor stores memory as plain Markdown in a folder you own (`VAULT_PATH`), so a
second agent process can recall a decision the first one saved.

## Cookbook

| File | MCP tools | Description |
|------|-----------|-------------|
| `agent_memory.py` | `remember_fact`, `search` | Saves a decision in one run, recalls it in a second run |

## Setup

The server runs self-hosted over stdio with `npx -y renor-engine mcp`, so no
Renor account is needed. It requires Node.js 22.16 or newer with `npx` on your
`PATH`, and the Python dependencies:

```bash
uv pip install "agno[mcp]" openai
export OPENAI_API_KEY=<your-api-key>
```

Memory is written to `tmp/renor-vault` next to the recipe (gitignored). Point
it elsewhere with `RENOR_VAULT_PATH=/path/to/vault`.

## Run

```bash
python agent_memory.py
```

The first run asks the agent to save a billing decision; the second run opens a
fresh MCP session and asks it to recall that decision. Because each run builds a
new agent, the second answer can only come from the vault on disk, not from chat
history.

## How It Works

1. `MCPTools(command="npx -y renor-engine mcp", env={"VAULT_PATH": ...})` starts
   the Renor server and merges `VAULT_PATH` into the inherited environment, so
   `PATH` still resolves `npx`.
2. The agent calls `remember_fact` with a subject, a predicate and an object.
   Renor appends the decision to `System/Memory Events Ledger.md` and indexes it.
3. The second run starts a new server process over the same vault. `search`
   returns the earlier ledger chunk and the structured fact, so the answer survives
   the conversation.

## More Information

- [Renor engine](https://github.com/renorai/renor-engine)
- [Agno's MCP integration](https://docs.agno.com/tools/mcp/overview)
- [Model Context Protocol](https://modelcontextprotocol.io/introduction)
