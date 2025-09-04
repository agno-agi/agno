# Troubleshooting

If your agent can't access the Hacker News tools, check:

1. That you have NPX installed and working properly
2. That your network allows NPX to download and run packages
3. That the tools are properly loaded by checking the Tools tab in the playground

Common issues include:

- NPX not being installed or configured properly
- Network restrictions preventing NPX from downloading packages
- Firewall or proxy settings blocking the Hacker News API

If you're having trouble, try running the NPX command manually in your terminal to see if it works:

```bash
npx -y @devabdultech/hn-mcp-server
```

This can help identify whether the issue is with NPX itself or with how it's being used in your Mastra configuration.

In the next step, we'll add the Filesystem MCP server to give your agent the ability to read and write files locally.
