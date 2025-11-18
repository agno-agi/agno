# MCP server using SSE transport

This cookbook shows how to use the `MCPTool` util with an MCP server using SSE transport.

1. Run the server with SSE transport
```bash
python cookbook/tools/mcp/sse_transport/server.py
```

2. Run the agent using the MCP integration connecting to our server
```bash
python cookbook/tools/mcp/sse_transport/client.py
```

Optionally set `refresh_connection` to `True` on the `MCPTools` configuration to refresh the MCP tools on each run.