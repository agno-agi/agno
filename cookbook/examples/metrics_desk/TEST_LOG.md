# Test Log - metrics_desk

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at a1aad6e5a).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

### metrics_desk.py

**Status:** PASS (server example: it serves until stopped, so the folder-wide runner sweep cannot complete it; verified manually with a real `fastmcp.Client`)

**Description:** A read-only warehouse behind a single MCP tool. Booted the server from this folder (fresh `tmp/`), then drove it with `fastmcp.Client` over `StreamableHttpTransport` at `http://localhost:7777/mcp`: listed tools, asked a revenue question, then asked it to delete the table.

**Result:** Tool list shows exactly one tool, with the docstring as its description:

```
TOOL ask_metrics {"additionalProperties": false, "properties": {"question": {"type": "string"}}, "required": ["question"], "type": "object"}
DESC Ask a question about the company's live orders database.
```

Revenue question over MCP returned the measured numbers and the query (condensed from the answer's markdown table; numbers and SQL unchanged):

```
REVENUE -> Total revenue by region on 2026-07-21
  apac 78.4 | emea 96.25 | us 512.0
  Query run: SELECT region, SUM(amount) AS total_revenue FROM orders
             WHERE day = '2026-07-21' GROUP BY region ORDER BY region;
```

Delete request: the agent ran the SQL and the driver refused it. Client-side result (markdown formatting stripped; wording and error text unchanged):

```
DELETE -> The database rejected the request because it is read-only.
  Query run: DROP TABLE orders;
  Error:
  Error running query: (sqlite3.OperationalError) attempt to write a readonly database
  [SQL: DROP TABLE orders;]
  (Background on this error at: https://sqlalche.me/e/20/e3q8)
```

Server-side, the same refusal printed a full traceback via `logger.exception` (`ERROR Error running query ... sqlite3.OperationalError: attempt to write a readonly database`). That is the system working, not a bug: the refusal comes from the SQLite driver, below the agent.

Also exercised: `GET /agents` on the same port with no auth header returned 200 with the full agent config, confirming the known limit that the REST surface is open by default while MCP exposes one tool.

---
