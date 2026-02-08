# Restructuring Plan: `cookbook/07_knowledge/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 33 (including 18 vector_db subdirectories) |
| Total `.py` files (non-`__init__`) | 187 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~73 (~39%) |
| Have section banners | ~19 (~10%) |
| Have `if __name__` gate | ~60 (~32%) |
| Contain emoji | ~5 (~3%) |
| Subdirectories with README.md | 8 / 33 |
| Subdirectories with TEST_LOG.md | 0 / 33 |

### Key Problems

1. **Sync/async directory split in `01_quickstart/`.** 16 sync files + 15 async files — near-identical pairs that differ only in `insert()` vs `ainsert()` and `print_response()` vs `aprint_response()`. Should be flattened like we did for workflows.

2. **Embedder batching pairs.** Many embedders have a base file and a `_batching` variant that only adds `enable_batch=True, batch_size=100`. These should be merged.

3. **Vector DB sync/async pairs.** Most vector_db subdirectories have sync + async + async_batching variants of the same example. The async variants should be merged into the sync base.

4. **Low documentation standards.** Only 39% have docstrings, 10% have banners, 32% have main gates.

5. **No TEST_LOG.md anywhere.** Zero directories have test logs.

6. **Emoji in 5 files.** Concentrated in embedders and vector_db.

### Overall Assessment

The largest cookbook section at 187 files. Well-organized by topic (01_quickstart, chunking, embedders, filters, readers, vector_db, etc.). The main redundancy comes from three patterns: (1) the sync/async split in 01_quickstart, (2) embedder base/batching pairs, and (3) vector_db sync/async pairs. Flattening these will significantly reduce file count.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 187 | ~140 |
| Style compliance | 0% | 100% |
| README coverage | 8/33 | All surviving directories |
| TEST_LOG coverage | 0/33 | All surviving directories |

---

## 2. Proposed Directory Structure

Flatten `01_quickstart/sync/` and `01_quickstart/async/` into `01_quickstart/`. Merge embedder batching pairs. Merge vector_db sync/async pairs.

```
cookbook/07_knowledge/
├── 01_quickstart/            # Getting started with knowledge (merged from sync/async)
├── chunking/                    # Chunking strategies (12 files, no change)
├── cloud/                       # Cloud knowledge patterns (4 files, no change)
├── custom_retriever/            # Custom retriever implementations (3 files, no change)
├── embedders/                   # Embedding providers (reduced from 29)
├── filters/                     # Knowledge filtering
│   └── vector_dbs/              # Filter examples per vector DB
├── protocol/                    # Protocol-based knowledge (1 file, no change)
├── readers/                     # File format readers (25 files, no change)
├── search_type/                 # Search strategies (3 files, no change)
├── testing_resources/           # Test data files (no change)
└── vector_db/                   # Vector database backends (18 subdirectories, reduced)
    ├── cassandra_db/
    ├── chroma_db/
    ├── clickhouse_db/
    ├── couchbase_db/
    ├── lance_db/
    ├── langchain/
    ├── lightrag/
    ├── llamaindex_db/
    ├── milvus_db/
    ├── mongo_db/
    ├── pgvector/
    ├── pinecone_db/
    ├── qdrant_db/
    ├── redis_db/
    ├── singlestore_db/
    ├── surrealdb/
    ├── upstash_db/
    └── weaviate_db/
```

### Changes from Current

| Change | Details |
|--------|---------|
| **RENAME + FLATTEN** `basic_operations/` → `01_quickstart/` | Rename directory. Merge ~15 sync/async pairs into parent. Remove sync/ and async/ subdirectories |
| **MERGE** embedder batching pairs | ~12 base+batching pairs → ~12 files (batching shown as variant in same file) |
| **MERGE** vector_db sync/async pairs | Per-DB: merge async variants into sync base files |

---

## 3. File Disposition Table

### `01_quickstart/` (31 → ~16, flatten sync/async)

The sync/ and async/ subdirectories contain near-identical files. Merge each pair into a single file in the parent directory.

**Sync files (16) — use as base, merge async in:**

| File | Disposition | New Location | Rationale |
|------|------------|-------------|-----------|
| `sync/01_from_path.py` | **REWRITE** | `01_quickstart/01_from_path.py` | Merge with async. Add banners, main gate |
| `sync/02_from_url.py` | **REWRITE** | `01_quickstart/02_from_url.py` | Merge with async |
| `sync/03_from_topic.py` | **REWRITE** | `01_quickstart/03_from_topic.py` | Merge with async |
| `sync/04_from_multiple_sources.py` | **REWRITE** | `01_quickstart/04_from_multiple_sources.py` | Merge with async |
| `sync/05_from_youtube_url.py` | **REWRITE** | `01_quickstart/05_from_youtube_url.py` | Merge with async |
| `sync/06_from_s3_path.py` | **REWRITE** | `01_quickstart/06_from_s3_path.py` | Merge with async |
| `sync/07_from_gcs_path.py` | **REWRITE** | `01_quickstart/07_from_gcs_path.py` | Merge with async |
| `sync/08_include_files.py` | **REWRITE** | `01_quickstart/08_include_files.py` | Merge with async |
| `sync/09_exclude_files.py` | **REWRITE** | `01_quickstart/09_exclude_files.py` | Merge with async |
| `sync/10_remove_contents.py` | **REWRITE** | `01_quickstart/10_remove_contents.py` | Merge with async |
| `sync/11_remove_vectors.py` | **REWRITE** | `01_quickstart/11_remove_vectors.py` | Merge with async |
| `sync/12_skip_if_exists.py` | **REWRITE** | `01_quickstart/12_skip_if_exists.py` | Merge with async |
| `sync/13_specify_reader.py` | **REWRITE** | `01_quickstart/13_specify_reader.py` | Merge with async |
| `sync/14_text_content.py` | **REWRITE** | `01_quickstart/14_text_content.py` | Merge with async |
| `sync/15_batching.py` | **REWRITE** | `01_quickstart/15_batching.py` | Merge with async |
| `sync/16_knowledge_instructions.py` | **KEEP + MOVE + FIX** | `01_quickstart/16_knowledge_instructions.py` | No async counterpart. Move, add banners, main gate |

**Async files (15) — merge into sync counterparts:**

| File | Disposition | Rationale |
|------|------------|-----------|
| `async/01_from_path.py` through `async/15_batching.py` | **MERGE INTO** sync counterparts | Near-identical. Async pattern added as section in main gate |

---

### `chunking/` (12 → 12, no change)

All files are unique chunking strategies. Style fixes only.

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_fixed_size_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `02_recursive_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `03_semantic_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `04_markdown_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `05_agentic_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `06_code_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `07_csv_row_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `08_custom_tokenizer.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `09_custom_chunking_strategy.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `10_sentence_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `11_paragraph_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `12_sliding_window_chunking.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `cloud/` (4 → 4, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `cloud_agentos.py` | **KEEP + FIX** | Add banners, main gate |
| `cloud_agentos_with_filters.py` | **KEEP + FIX** | Add banners, main gate |
| `cloud_knowledge.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `cloud_knowledge_data.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `custom_retriever/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `agent.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `retriever.py` | **KEEP + FIX** | Add banners, main gate |
| `retriever_usage.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `embedders/` (29 → ~17, merge batching pairs)

Merge each `*_embedder.py` + `*_embedder_batching.py` pair into a single file showing both modes. Keep standalone embedders that have no batching variant.

**Pairs to merge (12 pairs → 12 files):**

| Base File | Batching File | Disposition |
|-----------|--------------|-------------|
| `openai_embedder.py` | `openai_embedder_batching.py` | **REWRITE** — merge batching as variant |
| `cohere_embedder.py` | `cohere_embedder_batching.py` | **REWRITE** |
| `gemini_embedder.py` | `gemini_embedder_batching.py` | **REWRITE** |
| `mistral_embedder.py` | `mistral_embedder_batching.py` | **REWRITE** |
| `azure_openai_embedder.py` | `azure_openai_embedder_batching.py` | **REWRITE** |
| `aws_bedrock_embedder.py` | `aws_bedrock_embedder_batching.py` | **REWRITE** |
| `jina_embedder.py` | `jina_embedder_batching.py` | **REWRITE** |
| `voyage_embedder.py` | `voyage_embedder_batching.py` | **REWRITE** |
| `huggingface_embedder.py` | `huggingface_embedder_batching.py` | **REWRITE** |
| `together_embedder.py` | `together_embedder_batching.py` | **REWRITE** |
| `fireworks_embedder.py` | `fireworks_embedder_batching.py` | **REWRITE** |
| `vllm_embedder_remote.py` | `vllm_embedder_batching_remote.py` | **REWRITE**. Remove emoji |

**Standalone embedders (5 files, no batching variant):**

| File | Disposition | Rationale |
|------|------------|-----------|
| `ollama_embedder.py` | **KEEP + FIX** | No batching variant. Add docstring, banners, main gate |
| `sentence_transformer_embedder.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `langdb_embedder.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `nebius_embedder.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `custom_embedder.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `filters/` (9 → 9, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `filtering.py` | **KEEP + FIX** | Add docstring, main gate. Already has partial banners |
| `async_filtering.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `agentic_filtering.py` | **KEEP + FIX** | Add docstring, main gate |
| `filtering_with_output_schema.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `filtering_on_load.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `filtering_with_agent_conditions.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `filtering_with_team_conditions.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `filtering_with_invalid_keys.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `agentic_filtering_with_output_schema.py` | **KEEP + FIX** | Add docstring, banners, main gate |

### `filters/vector_dbs/` (9 → 9, no change)

All files demonstrate filtering with different vector DB backends. Each is unique.

| File | Disposition | Rationale |
|------|------------|-----------|
| All 9 files | **KEEP + FIX** | Add docstring, banners, main gate per file |

---

### `protocol/` (1 → 1, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `file_system.py` | **KEEP + FIX** | Add banners. Already has main gate |

---

### `readers/` (25 → 25, no change)

All reader files are unique — different file formats, different reader classes. No merges.

| File | Disposition | Rationale |
|------|------------|-----------|
| All 25 files | **KEEP + FIX** | Add docstring/banners/main gate per file. Remove emoji from `csv_field_labeled_reader.py` |

---

### `search_type/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `vector_search.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `keyword_search.py` | **KEEP + FIX** | Add docstring, banners, main gate |
| `hybrid_search.py` | **KEEP + FIX** | Add docstring, banners, main gate |

---

### `vector_db/` (59 → ~40, merge sync/async per DB)

Each vector DB subdirectory typically has: `xyz_db.py` (sync), `async_xyz_db.py` (async), `async_xyz_db_with_batch_embedder.py` (async + batching). Merge the async variants into the sync base. Keep specialized files (hybrid_search, etc.) as-is.

**General pattern per subdirectory:**
- Merge `async_xyz_db.py` → into `xyz_db.py`
- Merge `async_xyz_db_with_batch_embedder.py` → into `xyz_db.py` (as batching variant)
- Keep `xyz_db_hybrid_search.py` separate (different feature)
- Keep other specialized files separate

**Estimated reductions per subdirectory:**

| Subdirectory | Current | Target | Notes |
|-------------|---------|--------|-------|
| `pgvector/` | 5 | 3 | Merge async pair + batch into base. Keep hybrid_search, pgvector_with_langchain |
| `chroma_db/` | 5 | 3 | Merge async pair + batch. Keep hybrid_search. Remove emoji |
| `milvus_db/` | 6 | 4 | Merge async pair + batch. Keep hybrid_search, milvus_multi_search |
| `mongo_db/` | 5 | 3 | Merge async pair + batch. Keep hybrid_search |
| `qdrant_db/` | 5 | 3 | Merge async pair + batch. Keep hybrid_search |
| `weaviate_db/` | 4 | 2 | Merge async pair + batch. Keep hybrid_search |
| `lance_db/` | 5 | 4 | Merge async pair. Keep hybrid_search, lance_db_sample_data, lance_db_hybrid_search_native |
| `clickhouse_db/` | 3 | 2 | Merge async into sync. Keep 2 remaining |
| `couchbase_db/` | 2 | 2 | No async variant. Style fixes only |
| `pinecone_db/` | 3 | 2 | Merge async into sync. Keep namespace variant |
| `singlestore_db/` | 2 | 2 | No async variant. Style fixes only |
| `cassandra_db/` | 2 | 2 | No async variant. Style fixes only |
| `redis_db/` | 2 | 2 | No async variant. Style fixes only |
| `surrealdb/` | 3 | 2 | Merge async into sync. Keep |
| `upstash_db/` | 2 | 2 | No async variant. Style fixes only |
| `langchain/` | 1 | 1 | No async variant. Style fixes only |
| `lightrag/` | 2 | 2 | No async variant. Style fixes only |
| `llamaindex_db/` | 2 | 2 | No async variant. Style fixes only |

---

## 4. New Files Needed

No new files needed. The knowledge section has comprehensive coverage.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `07_knowledge/` (root) | EXISTS | **MISSING** |
| `01_quickstart/` | **MISSING** | **MISSING** |
| `chunking/` | EXISTS | **MISSING** |
| `cloud/` | **MISSING** | **MISSING** |
| `custom_retriever/` | EXISTS | **MISSING** |
| `embedders/` | EXISTS | **MISSING** |
| `filters/` | EXISTS | **MISSING** |
| `protocol/` | **MISSING** | **MISSING** |
| `readers/` | EXISTS | **MISSING** |
| `search_type/` | EXISTS | **MISSING** |
| `testing_resources/` | **MISSING** | N/A (data files) |
| `vector_db/` | EXISTS | **MISSING** |
| All 18 vector_db subdirs | Varies | **MISSING** |

---

## 6. Recommended Cookbook Template

```python
"""
<Knowledge Feature>
=============================

Demonstrates <what this file teaches> using Agno Knowledge.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
vector_db = PgVector(
    table_name="vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    name="My Knowledge Base",
    vector_db=vector_db,
)

knowledge.insert(
    name="Documents",
    path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What skills does Jordan Mitchell have?", markdown=True)
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (DB) → Create Knowledge Base → Create Agent → Run Agent
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Sync + async together** — When merging sync/async variants, show both in labeled sections within the `if __name__` block
8. **Self-contained** — Each file must be independently runnable
