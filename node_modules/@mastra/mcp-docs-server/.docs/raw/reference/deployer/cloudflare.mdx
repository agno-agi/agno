---
title: "Cloudflare Deployer"
description: "Documentation for the CloudflareDeployer class, which deploys Mastra applications to Cloudflare Workers."
---

# CloudflareDeployer

The `CloudflareDeployer` class handles deployment of standalone Mastra applications to Cloudflare Workers. It manages configuration, deployment, and extends the base [Deployer](/reference/deployer/deployer) class with Cloudflare specific functionality.

## Usage example

```typescript filename="src/mastra/index.ts" showLineNumbers copy
import { Mastra } from "@mastra/core/mastra";
import { CloudflareDeployer } from "@mastra/deployer-cloudflare";

export const mastra = new Mastra({
  // ...
  deployer: new CloudflareDeployer({
    projectName: "hello-mastra",
    routes: [
      {
        pattern: "example.com/*",
        zone_name: "example.com",
        custom_domain: true
      }
    ],
    workerNamespace: "my-namespace",
    env: {
      NODE_ENV: "production",
      API_KEY: "<api-key>"
    },
    d1Databases: [
      {
        binding: "DB",
        database_name: "my-database",
        database_id: "d1-database-id",
        preview_database_id: "your-preview-database-id"
      }
    ],
    kvNamespaces: [
      {
        binding: "CACHE",
        id: "kv-namespace-id"
      }
    ]
});
```

## Parameters

<PropertiesTable
  content={[
    {
      name: "projectName",
      type: "string",
      description: "Name of your worker project.",
      isOptional: true,
      defaultValue: "'mastra'",
    },
    {
      name: "routes",
      type: "CFRoute[]",
      description: "Array of route configurations for your worker. Each route requires: pattern (string), zone_name (string), custom_domain (boolean, optional).",
      isOptional: true,
    },
    {
      name: "workerNamespace",
      type: "string",
      description: "Namespace for your worker.",
      isOptional: true,
    },
    {
      name: "env",
      type: "Record<string, any>",
      description: "Environment variables to be included in the worker configuration.",
      isOptional: true,
    },
    {
      name: "d1Databases",
      type: "D1DatabaseBinding[]",
      description: "Array of D1 database bindings. Each binding requires: binding (string), database_name (string), database_id (string), preview_database_id (string, optional).",
      isOptional: true,
    },
    {
      name: "kvNamespaces",
      type: "KVNamespaceBinding[]",
      description: "Array of KV namespace bindings. Each binding requires: binding (string), id (string).",
      isOptional: true,
    },
  ]}
/>
