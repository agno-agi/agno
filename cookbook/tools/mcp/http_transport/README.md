# MCP server using SSE or Streamable HTTP transport

This cookbook shows how to use the `MCPTool` util with an MCP server using either SSE or Streamable HTTP transport.

## Using Streamable HTTP transport

1. Run the server with Streamable HTTP transport
```bash
python cookbook/tools/mcp/http_transport/server.py streamable-http
```

2. Run the agent using Streamable HTTP transport
```bash
python cookbook/tools/mcp/http_transport/client.py streamable-http
```

## Using SSE transport

1. Run the server with SSE transport
```bash
python cookbook/tools/mcp/http_transport/server.py sse
```

2. Run the agent using SSE transport
```bash
python cookbook/tools/mcp/http_transport/client.py sse
```