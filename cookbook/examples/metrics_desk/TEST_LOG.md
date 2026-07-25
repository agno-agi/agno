# Test Log - metrics_desk

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at a1aad6e5a).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

### metrics_desk.py

**Status:** PASS (direct run is a scripted demo and passes the runner sweep; the MCP surface is served by the folder's `__main__.py` and verified manually with a real `fastmcp.Client`)

**Description:** A read-only warehouse behind a single MCP tool. Two entry points, both verified: running the file asks the desk the revenue question and the delete demand directly and exits; running the folder serves the MCP endpoint, driven with `fastmcp.Client` over `StreamableHttpTransport` at `http://localhost:7777/mcp`.

**Result:** Direct run (fresh `tmp/`), exit 0: the revenue panel reported apac 78.4, emea 96.25, us 512.0 with the query, then the delete demand issued the SQL and printed the driver's refusal:

```
• run_sql_query(query=DROP TABLE orders;, limit=10)
Result
  Error running query: (sqlite3.OperationalError) attempt to write a readonly database
  [SQL: DROP TABLE orders;]
  (Background on this error at: https://sqlalche.me/e/20/e3q8)
```

The folder sweep (`cookbook_runner.py cookbook/examples -r -c 2`) reports all four examples PASS, this one in 13.3s.

Serving run: `python cookbook/examples/metrics_desk` launched from `cookbook/examples/`; `tmp/` stayed inside the example folder. Tool list shows exactly one tool, with the docstring as its description:

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
