# Connecting the Tool to Your Agent

Now that we've created our tool, we need to connect it to our agent. Go back to your `agents/financial-agent.ts` file and update it:

1. Import the tool:

```typescript
import { getTransactionsTool } from "../tools/get-transactions-tool";
```

2. Add the tool to your agent:

```typescript
export const financialAgent = new Agent({
  name: "Financial Assistant Agent",
  instructions: `ROLE DEFINITION
  // ... existing instructions ...
  
  TOOLS
  - Use the getTransactions tool to fetch financial transaction data.
  - Analyze the transaction data to answer user questions about their spending.`,
  model: openai("gpt-4o"),
  tools: { getTransactionsTool }, // Add our tool here
});
```

By adding the tool to your agent's configuration, you're making it available for the agent to use. The agent will now be able to call the `getTransactions` tool when it needs to access transaction data.

It's also important to update the agent's instructions to include information about the tool. This helps the agent understand when and how to use the tool to fulfill user requests.
