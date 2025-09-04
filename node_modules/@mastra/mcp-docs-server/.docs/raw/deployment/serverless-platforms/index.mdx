---
title: "Serverless Deployment"
description: "Build and deploy Mastra applications using platform-specific deployers or standard HTTP servers"
---

# Serverless Deployment

Standalone Mastra applications can be deployed to popular serverless platforms using one of our deployer packages:

- [Cloudflare](/docs/deployment/serverless-platforms/cloudflare-deployer)
- [Netlify](/docs/deployment/serverless-platforms/netlify-deployer)
- [Vercel](/docs/deployment/serverless-platforms/vercel-deployer)

Deployers **aren't** required when integrating Mastra with a framework. See [Web Framework Integration](/docs/deployment/web-framework) for more information.

For self-hosted Node.js server deployment, see the [Creating A Mastra Server](/docs/deployment/server) guide.

## Prerequisites

Before you begin, ensure you have:

- Node.js `v20.0` or higher
- If using a platform-specific deployer:
  - An account with your chosen platform
  - Required API keys or credentials

## LibSQLStore

`LibSQLStore` writes to the local filesystem, which is not supported in serverless environments due to their ephemeral nature. If you're deploying to a platform like Vercel, Netlify or Cloudflare, you **must remove** all usage of `LibSQLStore`.

Specifically, ensure you've removed it from both `src/mastra/index.ts` and `src/mastra/agents/weather-agent.ts`:

```typescript filename="src/mastra/index.ts" showLineNumbers
export const mastra = new Mastra({
  // ...
  storage: new LibSQLStore({ // [!code --]
    // stores telemetry, evals, ... into memory storage, if it needs to persist, change to file:../mastra.db // [!code --]
    url: ":memory:", // [!code --]
  })//[!code --]
});
```

```typescript filename="src/mastra/agents/weather-agent.ts" showLineNumbers
export const weatherAgent = new Agent({
 // ..
 memory: new Memory({  // [!code --]
   storage: new LibSQLStore({ // [!code --]
      url: "file:../mastra.db" // path is relative to the .mastra/output directory // [!code --]
   }) // [!code --]
 })//  [!code --]
});
```
