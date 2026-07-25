# Second Brain

Memory you own, curated and portable, behind your own MCP server: a private agent that remembers what you are building, and an endpoint that Claude Desktop, Cursor and your own scripts all read and write.

## The claim

A chat app cannot do this because the endpoint is yours: every AI app reads and writes the same store, and the store outlives any one vendor.

To be fair about what chat apps can do: ChatGPT and Claude both have memory, and within their own walls it works well. What they do not have is one curated store that Claude Desktop, Cursor and your own scripts all write into through an MCP server you run, keyed per user, on your disk. The differentiator here is the endpoint and the ownership, not the recall.

## Run it

From the repo root, with `OPENAI_API_KEY` set (the only key needed):

```bash
cd cookbook/examples/second_brain
../../../.venvs/demo/bin/python second_brain.py
```

Run it twice. The second run is a new process, so everything it recalls comes from the store the first run left in `tmp/second_brain.db`. To start the MCP server instead:

```bash
../../../.venvs/demo/bin/python second_brain.py --serve
```

## What you will see

First run: the capture session writes the note (and the learning machine saves memories in the background), then the recall session, a brand new session with no chat history, answers the question. Everything it knows came from the store the first session just filled.

```
• write_file(path=notes/harbor.md, content=Project: Harbor ...
  Decision: Use PostgreSQL advisory locks over SELECT FOR UPDATE SKIP LOCKED
  because workers are long-lived. ..., overwrite=False)
...
┃ You chose Postgres advisory locks for Harbor, instead of `SELECT FOR UPDATE ┃
┃ SKIP LOCKED`.                                                               ┃
...
Files in this user's brain:
  notes/harbor.md  (208 bytes)
```

Second run, a fresh process: the agent appends instead of rewriting (`append_file(path=notes/harbor.md, ..., unique=True)`), the note grows, and the recall works again with nothing in context.

```
Files in this user's brain:
  notes/harbor.md  (417 bytes)
```

The exact byte counts vary run to run; the note body is model-written. What holds is the shape: run one writes, run two appends and the file grows.

## Point an MCP client at it

With `--serve` running, the endpoint is `http://localhost:7777/mcp`. Client config:

```json
{
  "mcpServers": {
    "second-brain": {
      "url": "http://localhost:7777/mcp"
    }
  }
}
```

A client sees the eight built-in AgentOS tools, verified live: `get_agentos_config`, `run_agent`, `run_team`, `run_workflow`, `continue_run`, `cancel_run`, `get_sessions`, `get_session_runs`. Talk to the brain through `run_agent` with `agent_id="second-brain"` and a `user_id`:

```
run_agent(agent_id=second-brain, message=What did I decide about locking in Harbor?, user_id=ashpreet)
-> "You chose Postgres advisory locks for Harbor instead of SELECT ... FOR UPDATE SKIP LOCKED. ..."
```

## For production

Swap `SqliteDb(db_file="tmp/second_brain.db")` for `PostgresDb(db_url=...)`; sessions, learning stores and the filesystem all move with it. Put real authentication on the server before exposing it beyond localhost: both the REST API and `/mcp` are open by default. Drop `reload=True` from `serve()`.

## Known limits

- The templated namespace fails closed. When an MCP client calls `run_agent` without a `user_id`, the filesystem tool call fails (an `InvalidPathError` returned to the model as the tool result) and the agent reports it in prose (observed: "I don't have accessible project notes for you in this run").
- Namespaces are normalized and lowercased, so `Alice` and `alice` share a store.
- `run_agent` over MCP mints a fresh session per call unless the client echoes `session_id` back, which makes `add_history_to_context` inert over MCP. Durable recall still works, because it comes from the notes and the learning stores, not the session.
- `user_profile` stays empty until something profile-shaped (a name, a preferred name) appears. The unstructured recall you see here comes from `user_memory`.
