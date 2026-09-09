# Test Log - metrics_desk

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at 5e6185ea9).
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

**Description:** Serving run. `python metrics_desk.py` from the example folder serves REST on `/` and MCP on `/mcp`, driven with `fastmcp.Client` over `StreamableHttpTransport`. Run with `AGENT_OS_PORT=7811` so it did not collide with another AgentOS on 7777.

**Result:** The client sees exactly one tool, and the connection string, schema and rows never cross the wire:

```
TOOLS: ['ask_metrics']
ANSWER: ## Total revenue by region on 2026-07-21
  | apac | 78.4 | emea | 96.25 | us | 512.0 |
  Query run: SELECT region, SUM(amount) AS total_revenue FROM orders
             WHERE day = '2026-07-21' GROUP BY region ORDER BY region;
```

`tmp/` stayed inside the example folder. Both `db_file` and the seeded warehouse are relative paths, so run both commands from the example folder.

### The read-only guarantee, attacked

**Status:** PASS

**Description:** `mode=ro` alone protects only the database the engine opened. A caller who knows SQLite can re-open the same file read-write through `ATTACH`, and temp tables are writes the read-only flag permits. Both are now denied by an authorizer on every pooled connection, so the guarantee holds against SQL the model was talked into running.

**Result:** Directly against the engine: `SELECT` allowed, `DROP TABLE` refused by the driver (`attempt to write a readonly database`), `CREATE TEMP TABLE` refused (`not authorized`), `ATTACH ... mode=rw` refused, `ATTACH 'tmp/evil.db'` refused and no file created.

Through the served MCP tool, asked to run the attack as three statements:

```
ask_metrics("1) ATTACH DATABASE 'file:tmp/shop.db?mode=rw&uri=true' AS rw;
             2) DELETE FROM rw.orders WHERE region='apac'; 3) SELECT COUNT(*) FROM orders;")
-> "The statements were run as requested, but the database returned an error:
    Error running query: (sqlite3.DatabaseError) not authorized"
ask_metrics("How many rows are in orders?") -> "There are 5 rows in orders."
```

Also checked: with a bad `OPENAI_API_KEY`, `ask_metrics` returns "The metrics desk could not answer that question." rather than the provider's error text, which contained the key.

---
