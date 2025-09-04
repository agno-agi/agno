# Updating Your Agent's Instructions

Next, let's update your agent's instructions to include information about the GitHub tools:

```typescript
export const personalAssistantAgent = new Agent({
  name: "Personal Assistant",
  instructions: `
    You are a helpful personal assistant that can help with various tasks such as email, 
    monitoring github activity, and scheduling social media posts.
    
    You have access to the following tools:
    
    1. Gmail:
       - Use these tools for reading and categorizing emails from Gmail
       - You can categorize emails by priority, identify action items, and summarize content
       - You can also use this tool to send emails
    
    2. GitHub:
       - Use these tools for monitoring and summarizing GitHub activity
       - You can summarize recent commits, pull requests, issues, and development patterns
    
    Keep your responses concise and friendly.
  `,
  model: openai("gpt-4o"),
  tools: { ...mcpTools },
  memory,
});
```

By updating your agent's instructions to include information about the GitHub tools, you're helping it understand when and how to use these tools. The instructions provide context about what the GitHub tools can do, such as monitoring repository activity, checking pull requests and issues, and summarizing development patterns.

This context helps your agent make better decisions about when to use the GitHub tools and how to interpret the results they provide.
