# Test Log: knowledge

> Updated: 2026-02-12

### 01_team_with_knowledge.py

**Status:** FAIL (timeout)

**Description:** Team with LanceDb knowledge base -- downloads docs from URL, embeds with OpenAI, team queries knowledge.

**Result:** Timed out at 120s. URL content download and embedding takes too long for the large docs file.

---

### 02_team_with_knowledge_filters.py

**Status:** PASS

**Description:** Static metadata-based knowledge filtering -- downloads sample PDFs, inserts with metadata, filters by `user_id`.

**Result:** Completed successfully. Knowledge loaded from PDFs, filtered correctly by user_id metadata. Resume details extracted accurately.

---

### 03_team_with_agentic_knowledge_filters.py

**Status:** PASS

**Description:** AI-driven dynamic knowledge filtering using `enable_agentic_knowledge_filters=True`. Same sample data as 02.

**Result:** Completed successfully. Agentic filters applied correctly to retrieve relevant resume information.

---

### 04_team_with_custom_retriever.py

**Status:** FAIL (timeout)

**Description:** Custom team knowledge retriever using PgVector -- downloads docs from URL, embeds with OpenAI, custom retriever function.

**Result:** Timed out at 120s. URL content embedding into PgVector takes too long (large docs file). Processed ~300+ batches before timeout.

---
