# MCP Agents using Agno

Model Context Protocol (MCP) gives Agents the ability to interact with external systems through a standardized interface. Using Agno's MCP integration, you can build Agents that can connect to any MCP-compatible service.

## Examples in this Directory

1. Filesystem Agent (`filesystem.py`)

This example demonstrates how to create an agent that can explore, analyze, and provide insights about files and directories on your computer.

2. GitHub Agent (`github.py`)

This example shows how to create an agent that can explore GitHub repositories, analyze issues, pull requests, and more.

3. BGPT Agent (`bgpt.py`)

This example connects to the hosted BGPT MCP server for evidence-grounded scientific paper search. No local server required; free tier works without an API key.

4. Groq with Llama using MCP (`groq_mcp.py`)

This example uses the file system MCP agent with Groq running the Llama 3.3-70b-versatile model.

5. Include/Exclude Tools (`include_exclude_tools.py`)

This example shows how to include and exclude tools from the MCP agent. This is useful for reducing the number of tools available to the agent, or for focusing on a specific set of tools.

6. Multiple MCP Servers (`multiple_servers.py`)

This example shows how to use multiple MCP servers in the same agent. 

7. Sequential Thinking (`sequential_thinking.py`)

This example shows how to use the MCP agent to perform sequential thinking.

8. Airbnb Agent (`airbnb.py`)

This example shows how to create an agent that uses MCP and Gemini 2.5 Pro to search for Airbnb listings.

9. Structured Content Agent (`structured_content.py`)

This example connects to the hosted DeepWiki MCP server (public, no API key) to answer questions about GitHub repositories. It shows how a tool's `structuredContent` is preserved on `ToolResult.metadata["structured_content"]` and read back through a tool hook.

10. emem Agent (`emem.py`)

This example connects to the hosted emem MCP server (public, no API key) for shared, signed memory of the physical world. It shows an agent answering a plain-language question about a place by calling emem's MCP tools directly.

11. Peer Cash Agent (`peer_cash.py`)

This example connects to the published Peer Cash MCP server to discover fiat payout rails, read market-rate estimates, prepare unsigned Base USDC cash-outs, and track their order state. Wallet custody stays outside the agent: the server never accepts private keys, signs transactions, or broadcasts them.


12. Protocol Mode (`protocol_mode.py`)

This example shows how to choose which MCP protocol era `MCPTools` negotiates. The default `"legacy"` keeps the session-based era, where the connection is long-lived and `is_alive()` pings it. `"auto"` negotiates the newest era both sides support; the 2026-07-28 era is sessionless, so requests are self-contained and there is no connection to keep alive. Keep `"legacy"` for a server that gates access on initialize, holds per-session state, or elicits input mid-tool.

13. Magic Hour Agent (`magic_hour.py`)

This example connects to Magic Hour's hosted MCP server to create images and videos. It shows bearer authentication, long-running render handling, reuse of project IDs after timeouts, and exact output URL retrieval.

14. ParlayAPI Read-Only Discovery (`parlayapi.py`)

This example launches the published ParlayAPI MCP server with an explicit tool
allowlist. The default only discovers four public metadata tools locally. It
does not call an API endpoint or model, and ignores both ParlayAPI key environment
variables. Account creation, login email, checkout, preference changes and betting
verdict tools are excluded.

```bash
uv pip install "agno[mcp]==3.0.9" "parlayapi-mcp==0.3.7"
python cookbook/91_tools/mcp/parlayapi.py
```

To ask a model about public metadata, install `openai`, supply your own
`OPENAI_API_KEY` through your runtime's secret manager, and explicitly run:

```bash
python cookbook/91_tools/mcp/parlayapi.py --question "Which sports currently have live event counts? Summarize counts only."
```

For private data research, additionally supply your own `PARLAYAPI_KEY` (or
`PARLAY_API_KEY`) and add `--private`. This adds only sport catalog, odds and
props tools. `--private` alone still performs discovery without data or model
calls. Keys remain in the server environment, not tool arguments or prompts.
The fixed server origin is `https://parlay-api.com`; origin overrides are ignored.

An explicit `--question` run may call up to two tools and incurs your model's
charges; private data calls also consume the API account's applicable allowance.
Raw tool results can go to the configured OpenAI model. Use only a private
runtime and account permitted for that processing. No database or telemetry is
configured, but this does not disable your model provider's own retention.
Keep terminal output and research private. API access grants no public data
redisplay or redistribution rights. This example does not place bets.

This is a transport example, not a complete-data validator. Missing outcomes,
unknown source ages and scoped results must not be read as complete coverage.
The allowlist narrows tools exposed to this agent; it is not server-side access
control against a program that bypasses the toolkit. Review the allowlist when
upgrading the pinned server package.

References: [MCP server](https://pypi.org/project/parlayapi-mcp/),
[API documentation](https://parlay-api.com/docs),
[account signup](https://parlay-api.com/signup),
[current pricing](https://parlay-api.com/pricing),
[data-use terms](https://parlay-api.com/terms).

## Getting Started

### Prerequisites

Install Python 3.11 or newer. The Peer Cash example also requires Node.js 22 or
newer with `npx` available on your `PATH`.

Install the required Python dependencies:

```bash
uv pip install "agno[mcp]" openai
```

Export your API keys:

```bash
export OPENAI_API_KEY="your_openai_api_key"
```

> For the GitHub example, create a Github PAT following [these steps](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/github#setup).

### Run the Examples

```bash
python filesystem.py
python github.py
python bgpt.py
python structured_content.py
python emem.py
python peer_cash.py
python magic_hour.py
```

## How It Works

These examples use Agno to create agents that leverage MCP servers. The MCP servers provide standardized access to different data sources (filesystem, GitHub), and the agents use these servers to answer questions and perform tasks.

The workflow is:
1. Agent receives a query from the user
2. Agent determines which MCP tools to use
3. Agent calls the appropriate MCP server to get information
4. Agent processes the information and provides a response

## Customizing

You can modify these examples to:
- Connect to different MCP servers
- Change the agent's instructions
- Add additional tools
- Customize the agent's behavior

## More Information

- Read more about [MCP](https://modelcontextprotocol.io/introduction)
- Read about [Agno's MCP integration](https://docs.agno.com/tools/mcp)
