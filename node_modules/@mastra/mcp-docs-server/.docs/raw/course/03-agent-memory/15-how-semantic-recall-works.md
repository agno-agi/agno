# How Semantic Recall Works

Semantic recall uses vector embeddings of messages for similarity search. When a user sends a message, the system:

1. Creates an embedding (vector representation) of the message
2. Searches for similar message embeddings in the history
3. Retrieves the most relevant messages
4. Includes those messages and their surrounding context in the agent's context window

This allows the agent to "remember" relevant information from past conversations, even if they're not in the recent message history.

The embedding process converts text into a high-dimensional vector that captures the semantic meaning of the message. Messages with similar meanings will have similar vector representations, allowing the system to find relevant past messages even if they use different wording.

For example, if a user previously mentioned "I'm working on a project with a deadline next month" and later asks "When is my project due?", semantic recall can find the earlier message based on the semantic similarity between the question and the stored information.
