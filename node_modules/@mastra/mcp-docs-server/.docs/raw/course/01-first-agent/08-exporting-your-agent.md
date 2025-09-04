# Exporting Your Agent

To make your agent available to the playground, you need to export it through the Mastra class in your `src/mastra/index.ts` file.

First, import the necessary dependencies and your agent:

```typescript
import { Mastra } from "@mastra/core/mastra";
import { PinoLogger } from "@mastra/loggers";
import { LibSQLStore } from "@mastra/libsql";
import { financialAgent } from "./agents/financial-agent";

export const mastra = new Mastra({
  agents: {
    financialAgent,
  },
  storage: new LibSQLStore({
    url: ":memory:",
  }),
  logger: new PinoLogger({
    name: "Mastra",
    level: "info",
  }),
});
```

This creates a new Mastra instance that includes:

- Your financial agent
- In-memory storage for development
- A logger for debugging and monitoring

The Mastra class is the main entry point for your Mastra project. It's responsible for registering your agents and configuring the core services like storage and logging.
