# Metrics Desk

Your production database, answerable from any MCP client, without your credentials, your schema or your rows leaving your process. Only the answer crosses the wire.

## The claim

A chat app cannot do this because the connection is opened read-only before the model exists, and only the answer crosses the wire. Your credentials, your schema and your rows never leave the process.

To be fair about what chat apps can do: a chat app with a database connector can query a database, and for many teams that is enough. What it cannot do is hold the connection inside your network under a guarantee the model cannot talk its way past. The refusal you will see below comes from the SQLite driver, not from a system prompt, so it does not depend on the model behaving.

## Run it

From the repo root, with `OPENAI_API_KEY` set (the only key needed):

```bash
cd cookbook/examples/metrics_desk
../../../.venvs/demo/bin/python metrics_desk.py
```

The first run seeds `tmp/shop.db` with a writable engine, disposes it, and reopens the file read-only. Running the file asks the desk two questions and exits. To serve it for MCP clients, run the folder instead of the file:

```bash
.venvs/demo/bin/python cookbook/examples/metrics_desk
```

The folder's `__main__.py` pins the working directory to the example folder before serving, so this form works from the repo root or anywhere else.

## What you will see

Running the file: a revenue question comes back with the measured numbers and the query that produced them, then the delete demand reaches the database and the database itself refuses:

```
• run_sql_query(query=DROP TABLE orders;, limit=10)

Query run
  DROP TABLE orders;
Result
  Error running query: (sqlite3.OperationalError) attempt to write a readonly database
  [SQL: DROP TABLE orders;]
  (Background on this error at: https://sqlalche.me/e/20/e3q8)
```

At the same moment the log prints a full traceback containing `sqlite3.OperationalError: attempt to write a readonly database`. That is the system working: the write reached the driver and the driver said no. Over MCP the answers are the same, quoted in the TEST_LOG:

```
REVENUE -> Total revenue by region on 2026-07-21
  apac 78.4 | emea 96.25 | us 512.0
  Query run: SELECT region, SUM(amount) AS total_revenue FROM orders
             WHERE day = '2026-07-21' GROUP BY region ORDER BY region;
```

## Point an MCP client at it

The endpoint is `http://localhost:7777/mcp`. Client config:

```json
{
  "mcpServers": {
    "metrics-desk": {
      "url": "http://localhost:7777/mcp"
    }
  }
}
```

Exactly one tool is exposed, verified live:

```
ask_metrics(question: str) - Ask a question about the company's live orders database.
```

The connection string, the schema and the rows stay in this process; the client only ever sees the answer text.

## For production

Swap the seeded SQLite file for your real warehouse by handing `SQLTools` a read-only engine: in Postgres that is a dedicated role with `GRANT SELECT` only (ideally on a read replica), so the guarantee stays at the database layer where the model cannot negotiate with it. Swap `SqliteDb(db_file="tmp/metrics_desk.db")` for `PostgresDb(db_url=...)` for the agent's own storage, and put authentication on the server before exposing it beyond localhost.

## Known limits

- A refused write prints a full traceback server-side, because `SQLTools.run_sql_query` calls `logger.exception` before returning the driver's message to the model. Expected, and evidence the refusal is real.
- "Only one tool is exposed" is true of the MCP surface, not of the process: the REST API on the same port is unauthenticated by default, and `GET /agents` answers without auth. Lock the OS down before this leaves your machine.
- Read-only here is a property of the engine URI (`mode=ro`), enforced by SQLite. It is exactly as strong as the database-level guarantee you configure, no more.
