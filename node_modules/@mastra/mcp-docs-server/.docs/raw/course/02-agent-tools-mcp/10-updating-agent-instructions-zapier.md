# Updating Your Agent's Instructions

Next, let's update your agent's instructions to include information about the Zapier tools:

```typescript
export const personalAssistantAgent = new Agent({
  name: "Personal Assistant",
  instructions: `
    You are a helpful personal assistant that can help with various tasks such as email 
    and scheduling social media posts.
    
    You have access to the following tools:
    
    1. Gmail:
       - Use these tools for reading and categorizing emails from Gmail
       - You can categorize emails by priority, identify action items, and summarize content
       - You can also use this tool to send emails
    
    Keep your responses concise and friendly.
  `,
  model: openai("gpt-4o"),
  tools: { ...mcpTools },
  memory,
});
```

Updating your agent's instructions is crucial for helping it understand when and how to use the tools available to it. By explicitly mentioning the Gmail tools in the instructions, you're giving your agent context about what these tools do and when to use them.

This helps the agent make better decisions about which tools to use when responding to user requests, resulting in more helpful and accurate responses.
