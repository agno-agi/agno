# Integrations

Integration examples showing how to connect Agno agents with external platforms and services.

## Directories

### [a2a](./a2a/)
A2A (Agent-to-Agent) protocol examples, including a basic server/client flow.

### [discord](./discord/)
Discord bot examples, including media handling and memory-enabled bots.

### [memory](./memory/)
External memory service integrations (Mem0, Memori, and Zep).

### [observability](./observability/)
Tracing and monitoring integrations for agent and workflow execution.

### [rag](./rag/)
Third-party RAG and retrieval-stack integrations (Infinity reranker, LightRAG, LangChain + Qdrant).

### [surrealdb](./surrealdb/)
SurrealDB-backed memory manager integration examples.

### [entroly](./entroly/)
Context compression proxy that reduces LLM API costs by 70-95% for Agno agents. Uses knapsack optimization and cache alignment.

## Running Examples

Use the demo environment:

```bash
.venvs/demo/bin/python cookbook/92_integrations/<folder>/<file>.py
```

## Validation

Run the cookbook pattern checker on this section:

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/92_integrations --recursive
```
