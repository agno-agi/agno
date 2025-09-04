# Initializing MCP Tools

Once you have the configuration set up, you need to initialize the MCP tools:

```typescript
const mcpTools = await mcp.getTools();
```

This asynchronous call fetches all the available tools from the configured MCP servers. The `getTools()` method connects to each server specified in your configuration, retrieves the available tools, and returns them in a format that can be used by your Mastra agent.

The `mcpTools` object will contain all the tools provided by the MCP servers you've configured. We'll add these tools to our agent in the next step.
