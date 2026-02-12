# Test Log: knowledge

> Updated: 2026-02-11

### 01_team_with_knowledge.py

**Status:** FAIL

**Description:** Team with LanceDb knowledge base — downloads docs from URL, embeds with OpenAI, team queries knowledge.

**Result:** `lancedb` package not installed in demo venv. Import error at module level blocks execution.

---

### 02_team_with_knowledge_filters.py

**Status:** FAIL

**Description:** Static metadata-based knowledge filtering — downloads sample PDFs, inserts with metadata, filters by `user_id`.

**Result:** Same `lancedb` import error. Package not installed.

---

### 03_team_with_agentic_knowledge_filters.py

**Status:** FAIL

**Description:** AI-driven dynamic knowledge filtering — same sample data as 02, uses `enable_agentic_knowledge_filters=True`.

**Result:** Same `lancedb` import error. Package not installed.

---

### 04_team_with_custom_retriever.py

**Status:** PASS

**Description:** Custom team knowledge retriever using PgVector — downloads docs from URL, embeds with OpenAI, custom retriever function receives `RunContext.dependencies` for runtime context injection.

**Result:** Ran successfully (exit 0). Embedding is slow (~100s for URL content). Custom retriever received dependencies dict correctly. PgVector storage works.

---
