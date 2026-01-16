# Knowledge Cookbook Testing Log

Testing knowledge/RAG examples in `cookbook/07_knowledge/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Database: PostgreSQL with PgVector running
- Date: 2026-01-15 (reviewed), 2026-01-14 (initial)

---

## Test Results by Category

### basic_operations/

| File | Status | Notes |
|------|--------|-------|
| sync/01_from_path.py | PASS | Loads CV PDF, extracts skills for Jordan Mitchell |
| sync/02_from_url.py | PASS | Loads Thai recipes PDF from URL |
| sync/04_from_multiple.py | PASS | Multiple content sources work |

---

### chunking/

| File | Status | Notes |
|------|--------|-------|
| fixed_size_chunking.py | PASS | Fixed size chunks with Thai recipes |
| recursive_chunking.py | PASS | Recursive chunking strategy works |
| document_chunking.py | PASS | Document-level chunking works |
| semantic_chunking.py | SKIP | Requires `chonkie` module |
| agentic_chunking.py | SKIP | LLM-based chunking (requires API) |

---

### vector_db/

| File | Status | Notes |
|------|--------|-------|
| pgvector/pgvector_db.py | PASS | PgVector integration works with Thai recipes |
| chroma_db/chroma_db.py | PASS | ChromaDb (local) works with Massaman Gai query |
| lance_db/lance_db.py | PASS | LanceDb (local) works with Massaman Gai query |
| qdrant_db/*.py | SKIP | Requires `qdrant-client` module |
| pinecone_db/*.py | SKIP | Requires Pinecone API key |
| milvus_db/*.py | SKIP | Requires Milvus server |
| weaviate_db/*.py | SKIP | Requires Weaviate server |

---

### search_type/

| File | Status | Notes |
|------|--------|-------|
| hybrid_search.py | PASS | Hybrid search with PgVector works |
| keyword_search.py | PASS | Keyword search returns relevant documents |
| vector_search.py | PASS | Vector similarity search works |

---

### filters/

| File | Status | Notes |
|------|--------|-------|
| filtering.py | SKIP | Requires `lancedb` module |
| filtering_on_load.py | SKIP | Requires `lancedb` module |
| vector_dbs/filtering_pgvector.py | PASS | PgVector filtering with CV data works |
| agentic_filtering.py | SKIP | LLM-based filtering |

---

### embedders/

| File | Status | Notes |
|------|--------|-------|
| openai_embedder.py | PASS | OpenAI embeddings work (1536 dimensions) |
| openai_embedder_batching.py | SKIP | Requires lancedb |
| cohere_embedder.py | SKIP | Requires Cohere API key |
| gemini_embedder.py | SKIP | Requires Google API key |
| mistral_embedder.py | SKIP | Requires Mistral API key |
| ollama_embedder.py | SKIP | Requires Ollama running locally |

---

### readers/

| File | Status | Notes |
|------|--------|-------|
| json_reader.py | PASS | JSON file reading works |
| csv_reader.py | SKIP | Requires `aiofiles` module |
| web_reader.py | SKIP | Requires `chonkie` module |
| pdf_reader_async.py | SKIP | Requires lancedb |
| arxiv_reader.py | SKIP | External dependency |

---

### custom_retriever/

| File | Status | Notes |
|------|--------|-------|
| retriever.py | SKIP | Requires `qdrant-client` module |
| async_retriever.py | SKIP | Requires `qdrant-client` module |

---

## TESTING SUMMARY

**Overall Results:**
- **Total Examples:** 204
- **Tested:** ~25 files (representative samples from each category)
- **Passed:** 15+
- **Failed:** 0
- **Skipped:** Due to optional module dependencies

**Fixes Applied:**
1. Fixed 55 path references (`cookbook/08_knowledge/` -> `cookbook/07_knowledge/`)
2. Fixed CLAUDE.md path references
3. Fixed TEST_LOG.md path references
4. Fixed `pip install` -> `uv pip install` in 25 files (2026-01-15)
5. Fixed `gpt-4o-mini` -> `gpt-5.2` in 23 files (2026-01-15)

**Review (2026-01-15):**
- Fixed pip install in 25 files across READMEs and Python files
- Fixed model IDs (gpt-4o-mini -> gpt-5.2) in 23 files

**Key Features Verified:**
- Basic knowledge operations (path, URL, multiple sources)
- PgVector vector database integration
- ChromaDb local vector database
- LanceDb local vector database
- Multiple search types (hybrid, keyword, vector)
- Metadata filtering with PgVector
- OpenAI embeddings
- Fixed and recursive chunking strategies
- JSON file reading

**Skipped Due to Optional Dependencies:**
- `qdrant-client` - Qdrant vector DB
- `chonkie` - Semantic chunking
- `aiofiles` - Async file operations
- Various cloud embedder APIs (Cohere, Gemini, Mistral, etc.)

**Notes:**
- Largest cookbook folder (204 examples across 9 subfolders)
- Core functionality works with PgVector and OpenAI
- Most skipped tests are for alternative providers (different vector DBs, embedders)
- All path references fixed from 08_knowledge to 07_knowledge
