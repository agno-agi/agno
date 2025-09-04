# Updating Your Agent's Instructions

Next, let's update your agent's instructions to include information about the Filesystem tools:

```typescript
export const personalAssistantAgent = new Agent({
  name: "Personal Assistant",
  instructions: `
    You are a helpful personal assistant that can help with various tasks such as email, 
    monitoring github activity, scheduling social media posts, providing tech news,
    and managing notes and to-do lists.
    
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
    
    4. Filesystem:
       - You also have filesystem read/write access to a notes directory. 
       - You can use that to store info for later use or organize info for the user.
       - You can use this notes directory to keep track of to-do list items for the user.
       - Notes dir: ${path.join(process.cwd(), "notes")}
    
    Keep your responses concise and friendly.
  `,
  model: openai("gpt-4o"),
  tools: { ...mcpTools },
  memory,
});
```

By updating your agent's instructions to include information about the Filesystem tools, you're helping it understand when and how to use these tools. The instructions provide context about what the Filesystem tools can do, such as storing information for later use and keeping track of to-do list items.

This context helps your agent make better decisions about when to use the Filesystem tools and how to organize the information it stores. The inclusion of the notes directory path in the instructions ensures that your agent knows exactly where it can read from and write to.
