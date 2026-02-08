# Test Log: knowledge

> Updated: 2026-02-08 15:49:52

## Pattern Check

**Status:** PASS

**Result:** Checked 4 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/knowledge. Violations: 0

---

### 01_team_with_knowledge.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/knowledge/01_team_with_knowledge.py`.

**Result:** Exited with code 1. Tail: rom agno.vectordb.lancedb.lance_db import LanceDb, SearchType |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/vectordb/lancedb/lance_db.py", line 11, in <module> |     raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`") | ImportError: `lancedb` not installed. Please install using `pip install lancedb`

---

### 02_team_with_knowledge_filters.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/knowledge/02_team_with_knowledge_filters.py`.

**Result:** Exited with code 1. Tail: rom agno.vectordb.lancedb.lance_db import LanceDb, SearchType |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/vectordb/lancedb/lance_db.py", line 11, in <module> |     raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`") | ImportError: `lancedb` not installed. Please install using `pip install lancedb`

---

### 03_team_with_agentic_knowledge_filters.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/knowledge/03_team_with_agentic_knowledge_filters.py`.

**Result:** Exited with code 1. Tail: rom agno.vectordb.lancedb.lance_db import LanceDb, SearchType |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/vectordb/lancedb/lance_db.py", line 11, in <module> |     raise ImportError("`lancedb` not installed. Please install using `pip install lancedb`") | ImportError: `lancedb` not installed. Please install using `pip install lancedb`

---

### 04_team_with_custom_retriever.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/knowledge/04_team_with_custom_retriever.py`.

**Result:** Timed out before completion. Tail:                                                        | DEBUG =========================== user ===========================               | DEBUG Research the concept of AI agents, including their roles, functionalities, |       and examples from the knowledge base.                                      | DEBUG Creating new sync OpenAI client for model gpt-4o

---
