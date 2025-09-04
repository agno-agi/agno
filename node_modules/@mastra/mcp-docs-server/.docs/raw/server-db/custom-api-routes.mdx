---
title: "Custom API Routes"
description: "Expose additional HTTP endpoints from your Mastra server."
---

# Custom API Routes

By default Mastra automatically exposes registered agents and workflows via the server. For additional behavior you can define your own HTTP routes.

Routes are provided with a helper `registerApiRoute` from `@mastra/core/server`. Routes can live in the same file as the `Mastra` instance but separating them helps keep configuration concise.

```typescript filename="src/mastra/index.ts" copy showLineNumbers
import { Mastra } from "@mastra/core/mastra";
import { registerApiRoute } from "@mastra/core/server";

export const mastra = new Mastra({
  // ...
  server: {
    apiRoutes: [
      registerApiRoute("/my-custom-route", {
        method: "GET",
        handler: async (c) => {
          const mastra = c.get("mastra");
          const agents = await mastra.getAgent("my-agent");

          return c.json({ message: "Custom route" });
        },
      }),
    ],
  },
});
```

Once registered, a custom route will be accessible from the root of the server. For example:

```bash
curl http://localhost:4111/my-custom-route
```

Each route's handler receives the Hono `Context`. Within the handler you can access the `Mastra` instance to fetch or call agents and workflows.

To add route-specific middleware pass a `middleware` array when calling `registerApiRoute`.

```typescript filename="src/mastra/index.ts" copy showLineNumbers
import { Mastra } from "@mastra/core/mastra";
import { registerApiRoute } from "@mastra/core/server";

export const mastra = new Mastra({
  // ...
  server: {
    apiRoutes: [
      registerApiRoute("/my-custom-route", {
        method: "GET",
        middleware: [
          async (c, next) => {
            console.log(`${c.req.method} ${c.req.url}`);
            await next();
          }
        ],
        handler: async (c) => {
          return c.json({ message: "Custom route with middleware" });
        }
      })
    ]
  }
});
```
