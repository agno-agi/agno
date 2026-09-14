# Building Blocks

Core components you can configure to customize knowledge behavior.

## Prerequisites

1. Run Qdrant: `./cookbook/scripts/run_qdrant.sh`
2. Set `OPENAI_API_KEY` environment variable
3. For reranking: set `COHERE_API_KEY` environment variable
4. For the PgVector and Elasticsearch MMR examples: `./cookbook/scripts/run_pgvector.sh` or `./cookbook/scripts/run_elasticsearch.sh`

## Examples

| File | What It Shows |
|------|---------------|
| [01_chunking_strategies.py](./01_chunking_strategies.py) | All chunking strategies compared on the same document |
| [02_hybrid_search.py](./02_hybrid_search.py) | Vector, keyword, and hybrid search side by side |
| [03_reranking.py](./03_reranking.py) | Two-stage retrieval with Cohere reranking |
| [04_filtering.py](./04_filtering.py) | Dict filters, FilterExpr, and metadata tagging |
| [05_agentic_filtering.py](./05_agentic_filtering.py) | Agent-driven dynamic filter selection |
| [06_embedders.py](./06_embedders.py) | Comparing OpenAI and Ollama embedders |
| [07_mmr_diverse_results.py](./07_mmr_diverse_results.py) | MMR reranking for diverse, non-redundant results |
| [08_mmr_with_pgvector.py](./08_mmr_with_pgvector.py) | MMR over PgVector hybrid search |
| [09_mmr_with_elasticsearch.py](./09_mmr_with_elasticsearch.py) | MMR over Elasticsearch hybrid search |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/02_building_blocks/01_chunking_strategies.py
```

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
- [Chunking Strategies](https://docs.agno.com/knowledge/concepts/chunking/overview)
- [Embedders](https://docs.agno.com/knowledge/concepts/embedder/overview)
- [Vector Databases](https://docs.agno.com/knowledge/concepts/vector-db)
