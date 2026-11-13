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
| [06_embedders.py](./06_embedders.py) | Comparing OpenAI and Ollama embedders |
| [14_document_query_embeddings.py](./14_document_query_embeddings.py) | Document/query request purposes with an offline SDK recorder |

## Document and query embedding purposes

Document ingestion and vector-store batch writes pass `purpose="document"` to embedding
methods that explicitly accept it. Vector searches pass `purpose="query"`. Cohere and
Gemini use these hints to select their respective document and query retrieval task
types without modifying the shared embedder configuration. Explicit classification,
clustering, and other non-retrieval task types remain unchanged, including overrides in
`request_params`. Direct calls without `purpose` retain the configured task type.

Custom embedders with the original text-only signatures continue to work. To support
purpose hints, add an explicit optional `purpose` parameter to the relevant sync, async,
and batch methods. A generic `**kwargs` parameter alone does not opt in. The offline
example requires `google-genai` but no API key or database service.

Existing document vectors created with a query task type should be re-embedded before
mixing them with newly ingested document vectors. This change does not migrate stored
vectors or establish a retrieval-quality improvement. Bedrock task routing is outside
this stage and remains tracked separately.

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/02_building_blocks/01_chunking_strategies.py
```

## Further Reading

- [Knowledge Overview](https://docs.agno.com/knowledge/overview)
- [Chunking Strategies](https://docs.agno.com/knowledge/concepts/chunking/overview)
- [Embedders](https://docs.agno.com/knowledge/concepts/embedder/overview)
- [Vector Databases](https://docs.agno.com/knowledge/concepts/vector-db)
