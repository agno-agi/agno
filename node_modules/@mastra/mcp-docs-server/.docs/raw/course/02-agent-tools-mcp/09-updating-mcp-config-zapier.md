# Updating Your MCP Configuration

Now, let's update your MCP configuration in `src/mastra/agents/index.ts` to include the Zapier server:

```typescript
const mcp = new MCPClient({
  servers: {
    zapier: {
      url: new URL(process.env.ZAPIER_MCP_URL || ""),
    },
  },
});
```

This configuration tells your agent how to connect to the Zapier MCP server. The `zapier` key is a unique identifier for this server in your configuration, and the `url` property specifies the URL of the Zapier MCP server.

The `new URL()` constructor creates a URL object from the string provided by the environment variable. The `|| ""` part provides a default empty string in case the environment variable is not set, which prevents your application from crashing if the environment variable is missing.
