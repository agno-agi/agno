# Using Memory in Your Application

When using memory in your own application (outside the playground), you need to provide the `resourceId` and `threadId` with each agent call:

```typescript
// Example of using memory in your application
const response = await memoryAgent.stream("Hello, my name is Alice.", {
  resourceId: "user_alice",
  threadId: "conversation_123",
});
```

**Important:** Without these IDs, your agent will not use memory, even if memory is properly configured. The playground handles this for you, but you need to add IDs yourself when using memory in your application.

The `resourceId` should be a unique identifier for the user or entity that owns the conversation. This could be a user ID from your authentication system, an email address, or any other unique identifier.

The `threadId` should be a unique identifier for the specific conversation. This allows a single user to have multiple separate conversations with your agent, each with its own memory thread.

In a real application, you might generate these IDs when a user starts a new conversation and store them in your database or client-side storage to reuse in subsequent requests.
