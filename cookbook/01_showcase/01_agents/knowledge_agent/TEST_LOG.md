# Knowledge Agent Test Log

## Test Date: 2026-01-19

---

### Test 1: PTO Policy Query

**Status:** PASS

**Query:** "What is the PTO policy? How many days do I get?"

**Description:** Tests basic knowledge retrieval from employee handbook with specific information extraction.

**Result:**
- Correctly identified PTO allotment by tenure:
  - 1st year: 15 days
  - Years 2-5: 20 days
  - Years 5+: 25 days
- Included relevant rules (no rollover, HR portal submission)
- Cited source: Employee Handbook
- Suggested relevant follow-up questions

---

### Test 2: Knowledge Base Loading

**Status:** PASS

**Description:** Verified knowledge base loads correctly from the knowledge directory.

**Result:** Loaded 4 documents (product_guide.md, engineering_wiki.md, employee_handbook.md, onboarding_checklist.md) with 6 document chunks created.

---

### Setup Prerequisites

1. PostgreSQL with PgVector: `./cookbook/scripts/run_pgvector.sh`
2. Load knowledge: `python scripts/load_knowledge.py`

---

### Model Configuration

| Setting | Value |
|---------|-------|
| Model | `gpt-5.2` (OpenAIResponses) |
| Features | search_knowledge, add_history_to_context, enable_agentic_memory, markdown |
| Knowledge | Hybrid search (semantic + keyword) with PgVector |
| Embedder | text-embedding-3-small |

---

### Notes

- Agent uses ReasoningTools for planning search approach
- Hybrid search combines semantic and keyword matching for accurate retrieval
- Agent provides source citations with document and section references
- Suggests follow-up questions for continued assistance
- Warning: Database should be added for history and memory persistence
- Successfully updated from OpenAIChat to OpenAIResponses
