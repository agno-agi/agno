# Updating Your Agent's Instructions

Next, let's update your agent's instructions to include information about the Hacker News tools:

```typescript
export const personalAssistantAgent = new Agent({
  name: "Personal Assistant",
  instructions: `
    You are a helpful personal assistant that can help with various tasks such as email, 
    monitoring github activity, scheduling social media posts, and providing tech news.
    
    You have access to the following tools:
    
    1. Gmail:
       - Use these tools for reading and categorizing emails from Gmail
       - You can categorize emails by priority, identify action items, and summarize content
       - You can also use this tool to send emails
    
    2. GitHub:
       - Use these tools for monitoring and summarizing GitHub activity
       - You can summarize recent commits, pull requests, issues, and development patterns
    
    3. Hackernews:
       - Use this tool to search for stories on Hackernews
       - You can use it to get the top stories or specific stories
       - You can use it to retrieve comments for stories
    
    Keep your responses concise and friendly.
  `,
  model: openai("gpt-4o"),
  tools: { ...mcpTools },
  memory,
});
```

By updating your agent's instructions to include information about the Hacker News tools, you're helping it understand when and how to use these tools. The instructions provide context about what the Hacker News tools can do, such as searching for stories, retrieving top stories, and accessing comments.

This context helps your agent make better decisions about when to use the Hacker News tools and how to interpret the results they provide. When a user asks about tech news or specific topics on Hacker News, your agent will know to use these tools to provide relevant information.
