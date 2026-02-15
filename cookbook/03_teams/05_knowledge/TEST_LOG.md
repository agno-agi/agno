# Test Log: cookbook/03_teams/05_knowledge


## Pattern Check

**Status:** PASS

**Result:** Checked 5 file(s). Violations: 0

---

### 01_team_with_knowledge.py

**Status:** FAIL

**Description:** Validation issue: runtime

**Result:** Run: Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 168, in __init__
    import tantivy  # noqa: F401
    ^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'tantivy'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/ab/conductor/workspaces/agno/tallinn/cookbook/03_teams/05_knowledge/01_team_with_knowledge.py", line 26, in <module>
    vector_db=LanceDb(
              ^^^^^^^^
  File "/Users/ab/conductor/workspaces/agno/tallinn/libs/agno/agno/vectordb/lancedb/lance_db.py", line 170, in __init__
    raise ImportError(
ImportError: Please install tantivy-py `pip install tantivy` to use the full text search feature.

---

### 02_team_with_knowledge_filters.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### 03_team_with_agentic_knowledge_filters.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: code_before_first_section_banner | Run: completed

---

### 04_team_with_custom_retriever.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/05_knowledge/04_team_with_custom_retriever.py`.

**Result:** Executed successfully.

---

### 05_team_update_knowledge.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/05_knowledge/05_team_update_knowledge.py`.

**Result:** Executed successfully.

---
