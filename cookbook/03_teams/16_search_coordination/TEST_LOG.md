# Test Log: cookbook/03_teams/16_search_coordination


## Pattern Check

**Status:** PASS

**Result:** Checked 3 file(s). Violations: 0

---

### 01_coordinated_agentic_rag.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/16_search_coordination/01_coordinated_agentic_rag.py", line 20, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### 02_coordinated_reasoning_rag.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/16_search_coordination/02_coordinated_reasoning_rag.py", line 21, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### 03_distributed_infinity_search.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/knowledge/reranker/infinity.py", line 9, in <module>
    from infinity_client import AuthenticatedClient, Client
ModuleNotFoundError: No module named 'infinity_client'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/16_search_coordination/03_distributed_infinity_search.py", line 11, in <module>
    from agno.knowledge.reranker.infinity import InfinityReranker
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/knowledge/reranker/infinity.py", line 13, in <module>
    raise ImportError("infinity_client not installed, please run `pip install infinity_client`")
ImportError: infinity_client not installed, please run `pip install infinity_client`

---
