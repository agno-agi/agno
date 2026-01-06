# MCP server using Streamable HTTP transport

This cookbook shows how to use the `MCPTool` util with an MCP server using Streamable HTTP transport.

1. Run the server with Streamable HTTP transport
```bash
python cookbook/tools/mcp/streamable_http_transport/server.py
```

2. Run the agent using the MCP integration connecting to our server
```bash
python cookbook/tools/mcp/streamable_http_transport/client.py
```

Optionally set `refresh_connection` to `True` on the `MCPTools` configuration to refresh the MCP tools on each run.