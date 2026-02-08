# Implement `cookbook/07_knowledge/` Restructuring

You are restructuring the `cookbook/07_knowledge/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- Knowledge scripts set up vector databases, create knowledge bases, load documents, create agents, and run them.
- This is the **largest cookbook section** at 187 files. The goal is to reduce to ~140 files by merging three categories of redundant pairs.
- Every surviving file must comply with the style guide (see Template section below).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket changes across files using batch scripts or regex-based rewrites.** Every file configures a specific vector database, embedder, reader, or chunking strategy with unique setup. You must:

1. **Read each file individually** before making any changes.
2. **Understand what the file does** — its vector DB setup, embedder configuration, knowledge base definition, and agent configuration.
3. **Preserve the existing logic exactly** — only restructure the layout (add banners, docstring, main gate).
4. **For MERGE operations**, read ALL source files first, then combine their unique content thoughtfully.
5. **Preserve Docker setup commands** in docstrings — many files include `docker run` commands for starting vector databases.

## CRITICAL: Three Different Merge Patterns

This section has three distinct categories of merges. Each requires different handling:

### Pattern 1: 01_quickstart/ sync/async flatten (15 pairs)
The `01_quickstart/sync/` and `01_quickstart/async/` directories contain near-identical files. The only differences are `insert()` vs `ainsert()` and `print_response()` vs `aprint_response()`. Use the sync version as the base and add an async section in the main gate.

### Pattern 2: Embedder batching pairs (12 pairs)
Each embedder has a base file (`openai_embedder.py`) and a batching variant (`openai_embedder_batching.py`). The batching variant only adds `enable_batch=True, batch_size=100` to the embedder config. Merge by showing both standard and batching modes in the same file.

### Pattern 3: Vector DB sync/async pairs (~19 pairs)
Most vector_db subdirectories have `xyz_db.py` (sync) and `async_xyz_db.py` (async), plus sometimes `async_xyz_db_with_batch_embedder.py`. Merge async variants into the sync base file.

## CRITICAL: Emoji Removal

5 files contain emoji that must be removed:
- `readers/csv_field_labeled_reader.py`
- `embedders/vllm_embedder_remote.py`
- `embedders/vllm_embedder_batching_remote.py`
- `vector_db/chroma_db/chroma_db_hybrid_search.py`
- (check for any others during processing)

## Style Guide Template

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

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates. Preserve Docker setup instructions.
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup (vector DB) → Create Knowledge Base → Create Agent → Run Agent
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Sync + async together** — When merging, show both in labeled sections within the `if __name__` block
8. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Flatten 01_quickstart/ (31 → ~16 files)

1. For each of the 15 sync/async pairs in `01_quickstart/`:
   - Read both `sync/<file>.py` and `async/<file>.py`
   - Use sync as base, add async section in main gate
   - Write merged file to `01_quickstart/<file>.py`
   - Delete source files from sync/ and async/
2. Move `sync/16_knowledge_instructions.py` to `01_quickstart/` (no async counterpart)
3. Remove empty `sync/` and `async/` directories

### Phase 2: Merge Embedder Batching Pairs (29 → ~17 files)

For each of the 12 embedder pairs in `embedders/`:
1. Read both the base and `_batching` files
2. Show standard mode as primary, batching as a variant:
   ```python
   # Standard mode
   embedder = OpenAIEmbedder(id="text-embedding-3-small")

   # Batching mode (uncomment to use)
   # embedder = OpenAIEmbedder(id="text-embedding-3-small", enable_batch=True, batch_size=100)
   ```
3. Delete the `_batching` files

### Phase 3: Merge Vector DB Sync/Async Pairs (~59 → ~40 files)

For each vector_db subdirectory with async variants:
1. Read all files in the subdirectory
2. Merge `async_xyz_db.py` → into `xyz_db.py`
3. Merge `async_xyz_db_with_batch_embedder.py` → into `xyz_db.py` (as batching variant)
4. Keep specialized files separate (hybrid_search, sample_data, etc.)
5. Delete merged async source files

See RESTRUCTURE_PLAN.md Section 3 for per-subdirectory details.

### Phase 4: Style Fixes on All Remaining Files

For all files not already processed in Phases 1-3:
1. Read each file
2. Add module docstring if missing
3. Add section banners
4. Add `if __name__ == "__main__":` gate if missing
5. Remove emoji if present

### Phase 5: Clean Up Empty Directories

Remove `01_quickstart/sync/` and `01_quickstart/async/` after flattening.

### Phase 6: Create README.md and TEST_LOG.md

For every directory and subdirectory. See RESTRUCTURE_PLAN.md Section 5 for the full list.

### Phase 7: Validate

```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/07_knowledge/<subdir>
```

## Key Merge Examples

### Example: 01_quickstart sync/async pair

Before: `sync/01_from_path.py` + `async/01_from_path.py`

After: `01_quickstart/01_from_path.py`:
```python
if __name__ == "__main__":
    # --- Sync ---
    knowledge.insert(name="Documents", path="...")
    agent.print_response("What skills does Jordan Mitchell have?")

    # --- Async ---
    import asyncio
    asyncio.run(knowledge.ainsert(name="Documents", path="..."))
    asyncio.run(agent.aprint_response("What skills does Jordan Mitchell have?"))
```

### Example: Embedder batching merge

Before: `openai_embedder.py` + `openai_embedder_batching.py`

After: `openai_embedder.py`:
```python
# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Standard mode
embedder = OpenAIEmbedder(id="text-embedding-3-small")

# Batching mode (uncomment for batch processing)
# embedder = OpenAIEmbedder(id="text-embedding-3-small", enable_batch=True, batch_size=100)
```

### Example: Vector DB sync/async merge

Before: `pgvector/pgvector_db.py` + `pgvector/async_pgvector_db.py` + `pgvector/async_pgvector_db_with_batch_embedder.py`

After: `pgvector/pgvector_db.py` with async and batching as alternative sections.

## Important Notes

1. **Read before writing** — Do not apply changes to files you haven't read. Every file has unique vector DB and embedder configuration.
2. **Preserve vector DB setup** — Do not change connection strings, table names, Docker commands, or embedder configurations.
3. **Preserve specialized files** — hybrid_search, sample_data, native search, and other specialized files are kept separate (not merged).
4. **Different vector DBs, different classes** — Each vector DB uses different imports (`PgVector`, `ChromaDb`, `MilvusDb`, etc.). Don't mix them up.
5. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
6. **75 dashes** — `# ---------------------------------------------------------------------------` (75 dashes after `# `).
7. **Read the plan carefully** — The RESTRUCTURE_PLAN.md has per-subdirectory reduction targets and special notes.
8. **Emoji removal** — Check all files but especially `readers/csv_field_labeled_reader.py`, `embedders/vllm_*`, and `vector_db/chroma_db/`.
9. **testing_resources/** — This directory contains test data files (PDFs, CSVs, etc.). Do not modify these files.
