# Getting a Zapier MCP URL

First, you'll need to get a Zapier MCP URL. This typically requires:

1. Creating a Zapier account if you don't have one
2. Setting up the Zapier MCP integration by adding some tools (we will use Gmail in this example)
3. Getting your unique MCP URL

For this example, we'll use an environment variable to store the URL:

```bash
# Add this to your .env file
ZAPIER_MCP_URL=https://your-zapier-mcp-url.zapier.app
```

Using an environment variable is a good practice for storing sensitive information like API URLs. It keeps the URL out of your code, making it easier to manage and more secure. It also allows you to use different URLs for different environments (development, staging, production) without changing your code.
