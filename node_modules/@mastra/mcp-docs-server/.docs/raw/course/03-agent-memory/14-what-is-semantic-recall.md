# Implementing Semantic Recall

One of the quickest ways to take advantage of the configured vector store is to use semantic recall.

## What is Semantic Recall?

Semantic recall is a RAG-based (Retrieval-Augmented Generation) search that allows your agent to find and retrieve relevant past conversations based on the current user query. It's similar to how a person would search their memory for relevant information when asked a question.

For example, if a user asks "What did we discuss about my project last week?", semantic recall helps the agent find and retrieve those specific conversations, even if they happened many messages ago.

Semantic recall extends your agent's memory beyond the limitations of the recent conversation history. While conversation history only includes the most recent messages, semantic recall can find and retrieve relevant information from any point in the conversation history, regardless of when it occurred.
