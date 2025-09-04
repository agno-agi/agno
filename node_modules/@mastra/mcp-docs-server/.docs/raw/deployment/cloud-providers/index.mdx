---
title: "Cloud Providers"
description: "Deploy your Mastra applications to popular cloud providers."
---

## Cloud Providers

Standalone Mastra applications can be deployed to popular cloud providers, see one of the following guides for more information:

- [Amazon EC2](/docs/deployment/cloud-providers/amazon-ec2)
- [AWS Lambda](/docs/deployment/cloud-providers/aws-lambda)
- [Digital Ocean](/docs/deployment/cloud-providers/digital-ocean)
- [Azure App Services](/docs/deployment/cloud-providers/azure-app-services)

For self-hosted Node.js server deployment, see the [Creating A Mastra Server](/docs/deployment/server) guide.

## Prerequisites

Before deploying to a cloud provider, ensure you have:

- A [Mastra application](/docs/getting-started/installation)
- Node.js `v20.0` or higher
- A GitHub repository for your application (required for most CI/CD setups)
- Domain name management access (for SSL and HTTPS)
- Basic familiarity with server setup (e.g. Nginx, environment variables)

## LibSQLStore

`LibSQLStore` writes to the local filesystem, which is not supported in cloud environments that use ephemeral file systems. If you're deploying to platforms like **AWS Lambda**, **Azure App Services**, or **Digital Ocean App Platform**, you **must remove** all usage of `LibSQLStore`.

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
