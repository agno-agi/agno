# Text-to-SQL Agent Test Log

## Test Date: 2026-01-19

---

### Test 1: Basic Query - Most Races Won

**Status:** PASS

**Test:** "Who won the most races in 2019?"

**Description:** Tests basic aggregation query with date parsing and grouping.

**Result:** Agent correctly answered that Lewis Hamilton won the most races in 2019 with 11 wins. The SQL query used proper date parsing (`TO_DATE(rw.date, 'DD Mon YYYY')`) and aggregation.

**SQL Generated:**
```sql
SELECT
  rw.name AS driver,
  COUNT(*)::int AS wins
FROM race_wins rw
WHERE EXTRACT(YEAR FROM TO_DATE(rw.date, 'DD Mon YYYY')) = 2019
GROUP BY rw.name
ORDER BY wins DESC, driver ASC
LIMIT 50
```

---

### Test 2: Knowledge Base Integration

**Status:** PASS

**Description:** Verified that the knowledge base loads correctly from the knowledge directory and is searchable.

**Result:** Knowledge base loaded 6 documents (constructors_championship.json, race_wins.json, common_queries.sql, fastest_laps.json, race_results.json, drivers_championship.json).

---

### Setup Prerequisites

1. PostgreSQL with PgVector: `./cookbook/scripts/run_pgvector.sh`
2. Load F1 data: `python scripts/load_f1_data.py`
3. Load knowledge base: `python scripts/load_knowledge.py`

---

### Model Configuration

| Setting | Value |
|---------|-------|
| Model | `gpt-5.2` (OpenAIResponses) |
| Features | add_datetime_to_context, enable_agentic_memory, search_knowledge, add_history_to_context, markdown |
| Knowledge | Hybrid search with PgVector |
| Embedder | text-embedding-3-small |

---

### Notes

- Agent correctly uses semantic model to identify tables
- Knowledge base search is called before SQL generation
- Date parsing pattern is correctly applied for race_wins table
- Agent offers to save validated queries to knowledge base
- Successfully updated from OpenAIChat to OpenAIResponses
