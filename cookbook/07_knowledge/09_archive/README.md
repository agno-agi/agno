# Archive

Previous knowledge cookbooks preserved for reference and quick testing.
These files use the old structure (one file per feature/integration).
For the current cookbooks, see the parent directory.

## Quick Reference

| Folder | What's Inside | Files |
|--------|---------------|-------|
| [readers](./readers/) | Per-format readers + loading from path, URL, topic, YouTube, multiple sources | 29 |
| [chunking](./chunking/) | Every chunking strategy: fixed, recursive, semantic, document, code, CSV, markdown | 12 |
| [embedders](./embedders/) | Per-provider embedders: OpenAI, Cohere, Gemini, Mistral, Ollama, HuggingFace, etc. | 18 |
| [vector_dbs](./vector_dbs/) | Per-database examples: PgVector, Qdrant, Chroma, Lance, Milvus, Pinecone, Redis, etc. | 28 |
| [filters](./filters/) | Filtering, agentic filtering, per-DB filters, include/exclude, isolate vector search | 17 |
| [search_type](./search_type/) | Vector, keyword, and hybrid search | 3 |
| [cloud](./cloud/) | S3, GCS, Azure Blob, SharePoint, GitHub, AgentOS cloud | 6 |
| [custom_retriever](./custom_retriever/) | Custom retrieval functions, async, team retriever | 4 |
| [protocol](./protocol/) | KnowledgeProtocol: file system implementation | 1 |
| [os](./os/) | AgentOS with multiple knowledge instances | 1 |

Root files:

| File | What It Shows |
|------|---------------|
| `quickstart.py` | Basic Knowledge setup with ChromaDB |
| `knowledge_tools.py` | KnowledgeTools with search and analysis |
| `remove_content.py` | Removing knowledge content by ID |
| `remove_vectors.py` | Removing vectors from the database |
| `skip_if_exists.py` | Skipping duplicate inserts |
| `skip_if_exists_contentsdb.py` | Skip-if-exists with contents database tracking |
| `batching.py` | Batch embedding optimization |
| `knowledge_instructions.py` | Controlling automatic search-knowledge instructions |

## Running

```bash
.venvs/demo/bin/python cookbook/07_knowledge/09_archive/readers/csv_reader.py
```
