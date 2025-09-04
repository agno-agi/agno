# Updating Your MCP Configuration

Now, let's update your MCP configuration in `src/mastra/agents/index.ts` to include the Filesystem server:

```typescript
import path from "path";

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
    textEditor: {
      command: "pnpx",
      args: [
        `@modelcontextprotocol/server-filesystem`,
        path.join(process.cwd(), "..", "..", "notes"), // relative to output directory
      ],
    },
  },
});
```

This configuration tells MCP to run the Filesystem server using PNPX, pointing it to the "notes" directory we created. The `path.join(process.cwd(), "notes")` ensures that the path is correct regardless of where the application is run from.

The `textEditor` key is a unique identifier for this server in your configuration. The `command` property specifies that we want to use PNPX to run the server, and the `args` property provides the arguments to pass to PNPX, including the package name and the path to the notes directory.
