# Agent Concepts

Application of several agent concepts using Agno.

## Overview

### Async

Async refers to agents built with `async def` support, allowing them to seamlessly integrate into asynchronous Python applications. While async agents are not inherently parallel, they allow better handling of I/O-bound operations, improving responsiveness in Python apps.

For examples of using async agents, see /cookbook/agent_concepts/async/.

### Hybrid Search

Hybrid Search combines multiple search paradigms—such as vector similarity search and traditional keyword-based search—to retrieve the most relevant results for a given query. This approach ensures that agents can find both semantically similar results and exact keyword matches, improving accuracy and context-awareness in diverse use cases.

Hybrid search examples can be found under `/cookbook/agent_concepts/hybrid_search/`

### Knowledge

Agents use a knowledge base to supplement their training data with domain expertise.
Knowledge is stored in a vector database and provides agents with business context at query time, helping them respond in a context-aware manner.

Examples of Agents with knowledge can be found under `/cookbook/agent_concepts/knowledge/`

### Memory

Agno provides 3 types of memory for Agents:

1. Chat History: The message history of the session. Agno will store the sessions in a database for you, and retrieve them when you resume a session.
2. User Memories: Notes and insights about the user, this helps the model personalize the response to the user.
3. Summaries: A summary of the conversation, which is added to the prompt when chat history gets too long.

Examples of Agents using different memory types can be found under `/cookbook/agent_concepts/memory/`

### Multimodal

In addition to text, Agno agents support image, audio, and video inputs and can generate image and audio outputs.

Examples with multimodal input and outputs using Agno can be found under `/cookbook/agent_concepts/storage/`

### RAG

RAG (Retrieval-Augmented Generation) integrates external data sources with AI's generation processes to produce context-aware, accurate, and relevant responses. It leverages vector databases for retrieved information and enhances agent memory components like chat history and summaries to provide coherent and informed answers.

Examples of agentic RAG can be found under `/cookbook/agent_concepts/rag/`

### Reasoning

Reasoning is an *experimental feature* that enables an Agent to think through a problem step-by-step before jumping into a response. The Agent works through different ideas, validating and correcting as needed. Once it reaches a final answer, it will validate and provide a response.

Examples of agentic shwowing their reasoning can be found under `/cookbook/agent_concepts/reasoning/`

### Storage

Agents use storage to persist sessions and session state by storing them in a database.

Agents come with built-in memory, but it only lasts while the session is active. To continue conversations across sessions, we store agent sessions in a database like Sqllite or PostgreSQL.

Examples of using storage with Agno agents can be found under `/cookbook/agent_concepts/storage/`

### Teams

Multiple agents can be combined to form a team and complete complicated tasks as a cohesive unit.

Examples of using agent teams with Agno can be found under `/cookbook/agent_concepts/teams/`

### Tools

Agents use tools to take actions and interact with external systems. A tool is a function that an Agent can use to achieve a task. For example: searching the web, running SQL, sending an email or calling APIs.

Examples of using tools with Agno agents can be found under `/cookbook/agent_concepts/tools/`

### Vector DB's

Vector databases enable us to store information as embeddings and search for “results similar” to our input query using cosine similarity or full text search. These results are then provided to the Agent as context so it can respond in a context-aware manner using Retrieval Augmented Generation (RAG).

Examples of using vector databases with Agno can be found under `/cookbook/agent_concepts/vector_dbs/`
