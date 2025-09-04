# Managing Conversation History

In this step, we'll learn how to configure conversation history and understand memory threads in Mastra. Conversation history allows your agent to remember recent interactions, which is essential for maintaining context in ongoing conversations.

## Understanding Memory Threads

Mastra organizes memory into threads, which are records that identify specific conversation histories. Each thread uses two important identifiers:

1. **`threadId`**: A specific conversation ID (e.g., `support_123`)
2. **`resourceId`**: The user or entity ID that owns each thread (e.g., `user_alice`)

These identifiers allow memory to work properly outside of the playground. They help Mastra distinguish between different conversations and users, ensuring that the right memory is associated with the right conversation.

Without these identifiers, your agent would have no way to know which conversation history to retrieve when a user sends a message. The playground handles these identifiers automatically, but you'll need to manage them yourself when using memory in your own applications.
