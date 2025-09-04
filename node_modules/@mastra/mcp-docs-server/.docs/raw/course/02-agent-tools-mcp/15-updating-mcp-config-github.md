# Updating Your MCP Configuration

Now, let's update your MCP configuration in `src/mastra/agents/index.ts` to include the GitHub server:

```typescript
const mcp = new MCPClient({
  servers: {
    zapier: {
      url: new URL(process.env.ZAPIER_MCP_URL || ""),
    },
    github: {
      url: smitheryGithubMCPServerUrl,
    },
  },
});
```

This configuration adds the GitHub MCP server alongside the Zapier server we added in the previous step. The `github` key is a unique identifier for this server in your configuration, and the `url` property specifies the URL of the GitHub MCP server.

By adding multiple servers to your MCP configuration, you're building a more versatile agent that can access a wider range of tools and services. Each server adds its own set of capabilities to your agent.
