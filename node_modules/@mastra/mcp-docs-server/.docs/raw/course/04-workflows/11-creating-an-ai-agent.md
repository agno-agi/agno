# Creating an AI Agent

Learn how to create an Mastra agent that can be used within your workflows for more intelligent content processing.

## Creating a Content Analysis Agent

Create a new file for your agent in the `src/mastra/agents` directory. Use `content-agent.ts` as the name of the file with the following contents:

```typescript
// src/mastra/agents/content-agent.ts
import { openai } from "@ai-sdk/openai";
import { Agent } from "@mastra/core/agent";

export const contentAgent = new Agent({
  name: "Content Agent",
  description: "AI agent for analyzing and improving content",
  instructions: `
    You are a professional content analyst. Your role is to:
    1. Analyze content for clarity and engagement
    2. Identify the main themes and topics
    3. Provide a quality score from 1-10
    4. Suggest specific improvements
    
    Always provide constructive, actionable feedback.
  `,
  model: openai("gpt-4o-mini"),
});
```

## Understanding the Agent

- **Name**: Unique identifier for the agent
- **Description**: What the agent does
- **Instructions**: Detailed prompts that guide the AI's behavior
- **Model**: Which AI model to use (GPT-4o-mini is fast and cost-effective)

## Registering and Testing Your Agent

Open your `src/mastra/index.ts` file and add your agent (you may need to append it to the agents object in the Mastra class):

```typescript
// Import your workflow
import { contentAgent } from "./agents/content-agent";

export const mastra = new Mastra({
  // Register your agent here
  agents: {
    contentAgent,
  },
  // ...Existing code
});
```

You can test this agent in the Playground by navigating to the Agents tab and selecting `content-agent`. Use the chat interface to validate the agent is working.

The agent should provide analysis of the content, including themes, quality assessment, and improvement suggestions.

## Why Use Agents in Workflows?

Agents add intelligence to workflows by:

- **Understanding context**: AI can interpret meaning, not just process data
- **Generating insights**: Provide analysis that simple logic cannot
- **Adapting responses**: Give different feedback based on content type
- **Natural language output**: Communicate results in human-readable form

Your AI agent is ready! Next, you'll learn how to integrate it into a workflow step.
