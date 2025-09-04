# Updating Your MCP Configuration

Unlike the previous MCP servers that use URLs, the Hacker News MCP server can be run directly using NPX. This means we don't need to set up any external services or authentication.

Let's update your MCP configuration in `src/mastra/agents/index.ts` to include the Hacker News server:

```typescript
const mcp = new MCPClient({
  servers: {
    zapier: {
      url: new URL(process.env.ZAPIER_MCP_URL || ""),
    },
    github: {
      url: new URL(process.env.COMPOSIO_MCP_GITHUB || ""),
    },
    hackernews: {
      command: "npx",
      args: ["-y", "@devabdultech/hn-mcp-server"],
    },
  },
});
```

This configuration tells MCP to run the Hacker News server using NPX when needed. The `-y` flag automatically confirms any prompts, making it seamless to use.

Unlike the Zapier and GitHub servers that connect to external services via URLs, the Hacker News server is run locally using NPX. This approach is simpler because it doesn't require any authentication or external service setup.
