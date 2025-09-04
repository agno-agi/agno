# Creating the getTransactions Tool

Let's create a tool that fetches transaction data from a Google Sheet. We'll create a new file called `tools/get-transactions-tool.ts`.

First, create the new tool file at src/mastra/tools/get-transactions-tool.ts

Now add the necessary imports:

```typescript
import { createTool } from "@mastra/core/tools";
import { z } from "zod";
```

Now, let's create our tool:

```typescript
export const getTransactionsTool = createTool({
  id: "get-transactions",
  description: "Get transaction data from Google Sheets",
  inputSchema: z.object({}), // No input parameters needed
  outputSchema: z.object({
    csvData: z.string(),
  }),
  execute: async () => {
    return await getTransactions();
  },
});

const getTransactions = async () => {
  // This URL points to a public Google Sheet with transaction data
  const url =
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vTQWaCzJAFsF4owWRHQRLo4G0-ERv31c74OOZFnqLiTLaP7NweoiX7IXvzQud2H6bdUPnIqZEA485Ux/pub?gid=0&single=true&output=csv";
  const response = await fetch(url);
  const data = await response.text();
  return {
    csvData: data,
  };
};
```

This tool fetches transaction data from a public Google Sheet and returns it as a string. The `createTool` function from Mastra makes it easy to define the tool's ID, description, input and output schemas, and execution logic.
