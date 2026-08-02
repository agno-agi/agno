# Integrations

Partner integrations for Agno agents.

## Directories

### [parallel](./parallel/)
[Parallel](https://parallel.ai) web research for agents: Search, Extract, Task (deep research with citations), and Monitor APIs — from a single research agent up to a deployable AgentOS app.

### [surrealdb](./surrealdb/)
SurrealDB-backed memory manager integration examples.

## Moved

Some integrations now live closer to their topic:

| Integration | New location |
|-------------|--------------|
| Observability (Langfuse, Arize Phoenix, AgentOps, LangSmith, …) | [`cookbook/observability`](../observability/) |
| Memory providers (Mem0, Memori, Zep) | [`cookbook/11_memory/integrations`](../11_memory/integrations/) |
| RAG stacks (Infinity, LightRAG, LangChain + Qdrant) | [`cookbook/07_knowledge/05_integrations/rag`](../07_knowledge/05_integrations/rag/) |
| Discord bot | [`cookbook/05_agent_os/interfaces/discord`](../05_agent_os/interfaces/discord/) |
| A2A basic server/client | [`cookbook/05_agent_os/interfaces/a2a/basic_agent`](../05_agent_os/interfaces/a2a/basic_agent/) |

## Running Examples

Use the demo environment:

```bash
.venvs/demo/bin/python cookbook/integrations/<folder>/<file>.py
```

## Validation

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/integrations --recursive
```
