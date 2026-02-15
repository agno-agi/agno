# Test Log: cookbook/03_teams/15_distributed_rag


## Pattern Check

**Status:** PASS

**Result:** Checked 3 file(s). Violations: 0

---

### 01_distributed_rag_pgvector.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/15_distributed_rag/01_distributed_rag_pgvector.py`.

**Result:** Executed successfully.

---

### 02_distributed_rag_lancedb.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/15_distributed_rag/02_distributed_rag_lancedb.py", line 30, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### 03_distributed_rag_with_reranking.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/15_distributed_rag/03_distributed_rag_with_reranking.py", line 23, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---
