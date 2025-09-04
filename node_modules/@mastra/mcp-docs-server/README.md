# @mastra/mcp-docs-server

A Model Context Protocol (MCP) server that provides AI assistants with direct access to Mastra.ai's complete knowledge base. This includes comprehensive documentation with MDX support, a collection of production-ready code examples, technical blog posts, and detailed package changelogs. The server integrates with popular AI development environments like Cursor and Windsurf, as well as Mastra agents, making it easy to build documentation-aware AI assistants that can provide accurate, up-to-date information about Mastra.ai's ecosystem.

## Installation

### In Cursor

Create or update `.cursor/mcp.json` in your project root:

MacOS/Linux

```json
{
  "mcpServers": {
    "mastra": {
      "command": "npx",
      "args": ["-y", "@mastra/mcp-docs-server"]
    }
  }
}
```

Windows

```json
{
  "mcpServers": {
    "mastra": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@mastra/mcp-docs-server"]
    }
  }
}
```

This will make all Mastra documentation tools available in your Cursor workspace.
Note that the MCP server wont be enabled by default. You'll need to go to Cursor settings -> MCP settings and click "enable" on the Mastra MCP server.

### In Windsurf

Create or update `~/.codeium/windsurf/mcp_config.json`:

MacOS/Linux

```json
{
  "mcpServers": {
    "mastra": {
      "command": "npx",
      "args": ["-y", "@mastra/mcp-docs-server"]
    }
  }
}
```

Windows

```json
{
  "mcpServers": {
    "mastra": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@mastra/mcp-docs-server"]
    }
  }
}
```

This will make all Mastra documentation tools available in your Windsurf workspace.
Note that Windsurf MCP tool calling doesn't work very well. You will need to fully quit and re-open Windsurf after adding this.
If a tool call fails you will need to go into Windsurf MCP settings and re-start the MCP server.

### In a Mastra Agent

```typescript
import { MCPClient } from '@mastra/mcp';
import { Agent } from '@mastra/core/agent';
import { openai } from '@ai-sdk/openai';

// Configure MCP with the docs server
const mcp = new MCPClient({
  servers: {
    mastra: {
      command: 'npx',
      args: ['-y', '@mastra/mcp-docs-server'],
    },
  },
});

// Create an agent with access to all documentation tools
const agent = new Agent({
  name: 'Documentation Assistant',
  instructions: 'You help users find and understand Mastra.ai documentation.',
  model: openai('gpt-4'),
  tools: await mcp.getTools(),
});

// Or use toolsets dynamically in generate/stream
const response = await agent.stream('Show me the quick start example', {
  toolsets: await mcp.getToolsets(),
});
```

## Tools

### Documentation Tool (`mastraDocs`)

- Get Mastra.ai documentation by requesting specific paths
- Explore both general guides and API reference documentation
- Automatically lists available paths when a requested path isn't found

### Examples Tool (`mastraExamples`)

- Access code examples showing Mastra.ai implementation patterns
- List all available examples
- Get detailed source code for specific examples

### Blog Tool (`mastraBlog`)

- Access technical blog posts and articles
- Posts are properly formatted with code block handling
- Supports various date formats in blog metadata

### Changes Tool (`mastraChanges`)

- Access package changelogs
- List all available package changelogs
- Get detailed changelog content for specific packages
