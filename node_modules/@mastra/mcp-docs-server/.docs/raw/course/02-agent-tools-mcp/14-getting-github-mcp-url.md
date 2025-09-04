# Getting a Smithery GitHub MCP URL

First, you'll need to get a Smithery GitHub MCP URL. This typically requires:

1. Setting up a Smithery account
2. Creating a personal access token with your GitHub account
3. Getting your unique MCP URL via the Smithery packages

For this example, we'll use an environment variable to store the Smithery API key and profile name which can be found in the Smithery interface.

```bash
# Add this to your .env file
SMITHERY_API_KEY=your_smithery_api_key
SMITHERY_PROFILE=your_smithery_profile_name
```

Using an environment variable keeps your configuration secure and flexible. It also prevents sensitive information from being committed to your repository.

We will use the Smithery packages to authenticate and create a streamable HTTP URL for the MCP server configuration

```bash
pnpm install @smithery/sdk
```

```ts
import { createSmitheryUrl } from "@smithery/sdk";

const smitheryGithubMCPServerUrl = createSmitheryUrl(
  "https://server.smithery.ai/@smithery-ai/github",
  {
    apiKey: process.env.SMITHERY_API_KEY,
    profile: process.env.SMITHERY_PROFILE,
  },
);
```
