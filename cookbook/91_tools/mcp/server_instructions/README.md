# mcp/server_instructions

Shows `MCPTools` adopting the `instructions` an MCP server returns during the handshake.

- `server.py` declares `instructions=` on a FastMCP server with two tools that must be called in order.
- `client.py` connects over stdio, prints the loaded instructions, and runs the agent with
  `load_server_instructions` on and off.
