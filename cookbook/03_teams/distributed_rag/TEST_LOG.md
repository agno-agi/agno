# Test Log: distributed_rag

> Updated: 2026-02-08 15:49:52

## Pattern Check

**Status:** PASS

**Result:** Checked 3 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/distributed_rag. Violations: 0

---

### 01_distributed_rag_pgvector.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/distributed_rag/01_distributed_rag_pgvector.py`.

**Result:** Executed successfully. Duration: 29.14s. Tail:                            ┃ | ┃ Feel free to ask if you have any more questions or need further              ┃ | ┃ clarification on any step!                                                   ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### 02_distributed_rag_lancedb.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/distributed_rag/02_distributed_rag_lancedb.py`.

**Result:** Exited with code 1. Tail: rom agno.vectordb.lancedb.lance_db import LanceDb, SearchType |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/vectordb/lancedb/lance_db.py", line 11, in <module> |     raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`") | ImportError: `lancedb` not installed. Please install using `pip install lancedb`

---

### 03_distributed_rag_with_reranking.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/distributed_rag/03_distributed_rag_with_reranking.py`.

**Result:** Exited with code 1. Tail: ing.py", line 13, in <module> |     from agno.knowledge.reranker.cohere import CohereReranker |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/knowledge/reranker/cohere.py", line 10, in <module> |     raise ImportError("cohere not installed, please run pip install cohere") | ImportError: cohere not installed, please run pip install cohere

---
