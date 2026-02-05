# Dynamic Knowledge (Callable Knowledge)

This folder demonstrates **callable knowledge**: instead of passing a pre-built `Knowledge` instance into `Agent(...)`, you pass a **factory function** that is resolved at runtime using `RunContext` (and optionally `agent` / `session_state`).

## Why callable knowledge?

- **Per-user isolation**: each user gets their own vector DB namespace/collection.
- **Multi-tenant SaaS**: each tenant gets a physically isolated knowledge base.
- **Runtime configuration**: resolve the right knowledge based on `user_id`, `session_id`, `dependencies`, etc.

## Examples

| File | Pattern |
|------|---------|
| `01_user_namespaced_knowledge.py` | Per-user knowledge namespacing (one KB per user) |
| `02_multi_tenant_knowledge.py` | Multi-tenant KBs with tenant isolation + custom cache key |

## Caching

Callable tools/knowledge are cached by default (`cache_callables=True`).

- Default cache key: `user_id` (fallback to `session_id`).
- Override per kind:
  - `callable_knowledge_cache_key: Callable[[RunContext], str] | None`

Use `agent.clear_callable_cache(...)` / `await agent.aclear_callable_cache(...)` to invalidate and optionally close cached resources.

## Running

```bash
./scripts/demo_setup.sh
VIRTUAL_ENV=.venvs/demo uv pip install chromadb

# Requires OPENAI_API_KEY
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/07_knowledge/dynamic_knowledge/01_user_namespaced_knowledge.py
OPENAI_API_KEY=... .venvs/demo/bin/python cookbook/07_knowledge/dynamic_knowledge/02_multi_tenant_knowledge.py
```

