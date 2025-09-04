# Troubleshooting

If your agent can't access the Zapier tools, check:

1. That your Zapier MCP URL is correct in your environment variables
2. That you've properly set up the Zapier MCP integration
3. That the tools are properly loaded by checking the Tools tab in the playground

Common issues include:

- Incorrect or missing environment variables
- Network connectivity problems
- Authentication issues with the Zapier MCP server

If you're having trouble, try restarting your development server after making changes to your environment variables or configuration. This ensures that the changes are properly loaded.

In the next step, we'll add the GitHub MCP server to give your agent the ability to monitor and interact with GitHub repositories.
