# Building Blocks

Core components you can configure to customize knowledge behavior.

## Prerequisites

1. Run Qdrant: `./cookbook/scripts/run_qdrant.sh`
2. Set `OPENAI_API_KEY` environment variable
3. For reranking: set `COHERE_API_KEY` environment variable

## Examples

| File | What It Shows |
|------|---------------|
| [01_chunking_strategies.py](./01_chunking_strategies.py) | All chunking strategies compared on the same document |
| [02_hybrid_search.py](./02_hybrid_search.py) | Vector, keyword, and hybrid search side by side |
| [03_reranking.py](./03_reranking.py) | Two-stage retrieval with Cohere reranking |
| [04_filtering.py](./04_filtering.py) | Dict filters, FilterExpr, and metadata tagging |
| [05_agentic_filtering.py](./05_agentic_filtering.py) | Agent-driven dynamic filter selection |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/02_building_blocks/01_chunking_strategies.py
```
