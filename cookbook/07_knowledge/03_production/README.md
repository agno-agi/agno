# Production Patterns

Real-world patterns for deploying knowledge systems.

## Prerequisites

1. Run Qdrant: `./cookbook/scripts/run_qdrant.sh`
2. Set `OPENAI_API_KEY` environment variable

## Examples

| File | What It Shows |
|------|---------------|
| [01_multi_source_rag.py](./01_multi_source_rag.py) | Loading from files, URLs, and text in one batch |
| [02_knowledge_lifecycle.py](./02_knowledge_lifecycle.py) | Insert, skip-if-exists, remove, and status tracking |
| [03_multi_tenant.py](./03_multi_tenant.py) | Knowledge isolation per tenant with isolate_vector_search |
| [04_error_handling.py](./04_error_handling.py) | Idempotent inserts, batch error handling, verification |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/03_production/01_multi_source_rag.py
```

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
