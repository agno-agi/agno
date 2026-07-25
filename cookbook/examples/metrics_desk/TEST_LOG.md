# Test Log - metrics_desk

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at 164f9a6c1).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

### test.py

**Status:** PASS

**Description:** The CLI driver: ask the desk for revenue by region, then tell it to delete the table. The refusal comes from the SQLite driver, below the agent, so the guarantee does not depend on the model behaving.

**Result:** Fresh `tmp/`, exit 0. The revenue answer reported apac 78.4, emea 96.25, us 512.0 with the query it ran. The delete demand reached the database and was refused:

```
• run_sql_query(query=DROP TABLE orders;, limit=10)
Result
  Error running query: (sqlite3.OperationalError) attempt to write a readonly database
  [SQL: DROP TABLE orders;]
  (Background on this error at: https://sqlalche.me/e/20/e3q8)
```

Server-side the same refusal prints a full traceback via `logger.exception`. That is the system working, not a bug.

### metrics_desk.py

**Status:** PASS

**Description:** Serving run. `python metrics_desk.py` from the example folder now serves directly (the folder's `__main__.py` is gone), driven with `fastmcp.Client` over `StreamableHttpTransport`. Port moved to 7801 for this pass because another AgentOS held 7777.

**Result:** The client sees exactly one tool, and the connection string, schema and rows never cross the wire:

```
TOOLS: ['ask_metrics']
ANSWER: ## Total revenue by region on 2026-07-21
  | apac | 78.4 | emea | 96.25 | us | 512.0 |
  Query run: SELECT region, SUM(amount) AS total_revenue FROM orders
             WHERE day = '2026-07-21' GROUP BY region ORDER BY region;
```

`tmp/` stayed inside the example folder. Both `db_file` and the seeded warehouse are relative paths, so run both commands from the example folder.

---
