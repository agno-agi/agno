# Updating Your Agent

Let's update your agent to use the MCP tools. Modify your agent definition to include the MCP tools:

```typescript
export const personalAssistantAgent = new Agent({
  name: "Personal Assistant",
  instructions: `
    You are a helpful personal assistant that can help with various tasks.
    
    Keep your responses concise and friendly.
  `,
  model: openai("gpt-4o"),
  tools: { ...mcpTools }, // Add MCP tools to your agent
});
```

By spreading the `mcpTools` object into your agent's `tools` property, you're making all the tools from your configured MCP servers available to your agent. This allows your agent to access and use these tools when responding to user requests.

As we add more MCP servers in the upcoming steps, the `mcpTools` object will automatically include tools from those servers as well, giving your agent an expanding set of capabilities.
