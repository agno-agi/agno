# Reference Guides

Decision guides and comparison tables for choosing the right components.

## Guides

| Guide | What It Covers |
|-------|---------------|
| [vector_db_comparison.md](./vector_db_comparison.md) | Feature matrix for all 14+ vector databases |
| [embedder_comparison.md](./embedder_comparison.md) | All embedding providers with dimensions and cost |
| [chunking_decision_guide.md](./chunking_decision_guide.md) | When to use which chunking strategy |

## Quick Recommendations

- **Vector DB**: Start with PgVector for production
- **Embedder**: Start with OpenAI text-embedding-3-small
- **Chunking**: Start with Recursive Chunking (chunk_size=500)
- **Search**: Start with Hybrid Search
