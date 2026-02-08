# Test Log: distributed_rag

> Updated: 2026-02-08 00:52:28 

## Pattern Check

**Status:** PASS

**Result:** Checked 3 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/distributed_rag. Violations: 0

---

### 01_distributed_rag_pgvector.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/distributed_rag/01_distributed_rag_pgvector.py`.

**Result:** Completed successfully (exit 0) in 41.86s. Tail: ┃ milk soup!                                                                   ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### 02_distributed_rag_lancedb.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/distributed_rag/02_distributed_rag_lancedb.py`.

**Result:** Exited with code 1 in 0.36s. Tail: File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/vectordb/lancedb/lance_db.py", line 11, in <module> | raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`") | ImportError: `lancedb` not installed. Please install using `pip install lancedb`

---

### 03_distributed_rag_with_reranking.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/distributed_rag/03_distributed_rag_with_reranking.py`.

**Result:** Exited with code 1 in 0.25s. Tail: File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/knowledge/reranker/cohere.py", line 10, in <module> | raise ImportError("cohere not installed, please run pip install cohere") | ImportError: cohere not installed, please run pip install cohere

---
