# Test Log - second_brain

Tested 2026-07-25 against `gpt-5.6` (via `model="openai:gpt-5.6"`, which resolves to OpenAIResponses),
agno 2.8.2 (source tree at 5e6185ea9). Entries quote tool calls and printed state.
Model prose varies run to run and is paraphrased.

### test.py

**Status:** PASS

**Description:** Durable, owned memory across a session boundary. The driver captures a decision in one session, then asks for it back in a brand new session that shares no history, and finally lists the files in that user's namespace.

**Result:** Cold run (`rm -rf tmp` first), exit 0. The capture session wrote the memory and the note in the same turn:

```
• update_user_memory(task=Remember that Alice is building Harbor, a Postgres-backed
  job queue in Rust ... prefers terse answers with no bullet lists.)
• append_file(path=notes/harbor.md, content=Project: Harbor - a Postgres-backed job
  queue in Rust. Decision: Use PostgreSQL advisory locks instead of SELECT FOR UPDATE
  SKIP LOCKED because workers are long-lived., unique=True)
```

The recall session, a fresh session id with nothing in context, answered: "You chose PostgreSQL advisory locks instead of `SELECT FOR UPDATE SKIP LOCKED` because Harbor's workers are long-lived." Final print: `notes/harbor.md  (170 bytes)`.

The note body is model-written, so byte counts and wording vary run to run. What holds is the shape: the capture session writes, the recall session answers from the store, and a second process sees both.

### second_brain.py

**Status:** PASS

**Description:** Serving run. `python second_brain.py` serves REST on `/` and MCP on `/mcp`. Verified over REST with three callers, and over MCP with a real `fastmcp.Client`.

**Result:** `GET /config` reports `agents: [('second-brain', 'Second Brain')]`, the id MCP clients address. Three runs against `POST /agents/second-brain/runs`:

```
user_id=alice@example.com -> "You're building Harbor, a Postgres-backed job queue in Rust,
                              using advisory locks for its long-lived workers."
user_id=riya              -> "I don't have any projects recorded for you yet."
no user_id                -> • list_files -> "Error: this agent's files require user_id for
                              this run and none was provided."
                              "I couldn't access your note files because no user_id was provided."
```

The second and third are the point: notes are per user, and the templated namespace `brain/{user_id}` fails closed rather than falling back to a shared store.

Over MCP the client sees the eight built-in AgentOS tools, and `run_agent` reaches the same brain. `run_agent(agent_id="second-brain", user_id="dana@example.com", ...)` both read the store and wrote a new decision that a later REST call read back. `user_id` is the load-bearing argument here: an MCP client that omits it gets the fail-closed error above rather than someone else's notes.

`db_file` is relative, so run the CLI and the server from the example folder or they land in different stores.

---
