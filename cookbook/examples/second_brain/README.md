# Second Brain

Memory you own, curated and portable, behind your own MCP server: a private agent that remembers what you are building, and an endpoint that Claude Desktop, Cursor and your own scripts all read and write.

## The claim

A chat app cannot do this because the endpoint is yours: every AI app reads and writes the same store, and the store outlives any one vendor.

To be fair about what chat apps can do: ChatGPT and Claude both have memory, and within their own walls it works well. What they do not have is one curated store that Claude Desktop, Cursor and your own scripts all write into through an MCP server you run, keyed per user, on your disk. The differentiator here is the endpoint and the ownership, not the recall.

## Run it

From the repo root, with `OPENAI_API_KEY` set (the only key needed):

```bash
# Drive the brain from the CLI: capture in one session, recall in a new one
.venvs/demo/bin/python cookbook/examples/second_brain/test.py

# Serve the same brain: REST on /, MCP on /mcp
.venvs/demo/bin/python cookbook/examples/second_brain/second_brain.py
```

Both commands share one store at `cookbook/examples/second_brain/tmp/second_brain.db`, whichever directory you launch them from, so anything the CLI captures is also there over REST and MCP. Serving needs `agno[os,mcp]`; the demo venv has it.

## What you will see

`test.py` captures a decision in one session, prints what the learning machine extracted in the background, then answers from a brand new session with no chat history. Everything the second session knows came from the store the first one filled.

```
--- Session 1: capture a decision ---
• write_file(path=notes/harbor.md, content=# Harbor
  Postgres-backed job queue in Rust.
  ## Decisions
  - Use PostgreSQL advisory locks instead of `SELECT FOR UPDATE SKIP LOCKED`
  because workers are long-lived. ..., overwrite=False)

--- What it learned about you, in the background ---
  [9f422e45] Building Harbor, a Postgres-backed job queue in Rust; chose
  advisory locks over SELECT FOR UPDATE SKIP LOCKED because workers are
  long-lived.
  [75f34344] Prefers terse answers without bullet lists.

--- Session 2: a new session, nothing in context ---
┃ You chose Postgres advisory locks instead of `SELECT FOR UPDATE SKIP LOCKED` ┃
┃ because Harbor's workers are long-lived.                                     ┃

--- Files in this user's brain ---
  notes/harbor.md  (212 bytes)
```

Run it again and the agent reads the note first, then appends what is new instead of rewriting it. The note body is model-written, so byte counts and wording vary run to run; the shape holds.

## Test it in AgentOS

Serve it, then open the AgentOS UI against `http://localhost:7777`. Use the same `user_id` throughout: notes live under `brain/{user_id}`, so a different id is a different brain. The notes are not a UI tab; ask the agent to list them, or run `test.py` to print them.

| Say this | What proves the point |
| --- | --- |
| "I'm building Harbor, a Postgres-backed job queue in Rust. We picked advisory locks over SELECT FOR UPDATE SKIP LOCKED because workers are long-lived." | `write_file(path=notes/harbor.md)`, plus two memories in the Learnings tab |
| In a new session: "What did I decide about locking in Harbor?" | The reason comes back with nothing in context |
| "Update on Harbor: retries move to exponential backoff, 30s cap." | `append_file(..., unique=True)` on the same file, not a rewrite |
| "New project: Atlas, a Next.js dashboard. Decision: server components only." | A second file, `notes/atlas.md`, and Harbor untouched |
| "What am I working on?" | It lists and reads the notes, and both projects come back |
| "Which of my projects touch Postgres?" | `search_content` across the notes rather than a guess |
| "Correction: Harbor is in Go, not Rust." then ask again in a new session | The note is edited and the stale fact is gone from the answer |
| "Call me Ash." | The user profile fills in; it stays empty until something profile-shaped arrives |
| Switch `user_id` and ask "What am I working on?" | Nothing. The other user's notes are invisible, not merged |
| Send a run with no `user_id` | Every file tool fails closed and the agent says it has no notes |
| Restart the server and ask the locking question again | Same answer. It is the store, not the process |

## Point an MCP client at it

With the server running, the endpoint is `http://localhost:7777/mcp`. Client config:

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

Swap `SqliteDb` for `PostgresDb(db_url=...)`; sessions, learning stores and the filesystem all move with it. Put real authentication on the server before exposing it beyond localhost: both the REST API and `/mcp` are open by default. Drop `reload=True` from `serve()`.

## Known limits

- The templated namespace fails closed. When an MCP client calls `run_agent` without a `user_id`, the filesystem tool call fails (an `InvalidPathError` returned to the model as the tool result) and the agent reports it in prose (observed: "I don't have accessible project notes for you in this run").
- Namespaces are normalized and lowercased, so `Alice` and `alice` share a store.
- `run_agent` over MCP mints a fresh session per call unless the client echoes `session_id` back, which makes `add_history_to_context` inert over MCP. Durable recall still works, because it comes from the notes and the learning stores, not the session.
- `user_profile` stays empty until something profile-shaped (a name, a preferred name) appears. The unstructured recall you see here comes from `user_memory`.
