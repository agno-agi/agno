# Test Log - second_brain

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at a1aad6e5a).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

### second_brain.py

**Status:** PASS

**Description:** Durable, owned memory across a session boundary. The scripted demo captures a decision in one session, then recalls it in a brand new session with no shared history. The warm run is a separate process, so the recall can only come from the store. `--serve` exposes the same brain over MCP, verified with a real `fastmcp.Client`.

**Result:** Cold run (`rm -rf tmp` first): the capture session called `write_file(path=notes/harbor.md, content=Project: Harbor ... Decision: Use PostgreSQL advisory locks over SELECT FOR UPDATE SKIP LOCKED because workers are long-lived. ..., overwrite=False)` and logged `Wrote 208 bytes to notes/harbor.md`. The learning machine saved three user memories in the background (`add_memory` x3: the project, the locking decision, the terseness preference) and created entity `project/harbor` with three facts. The recall session, a fresh session id, answered that Harbor uses advisory locks because workers are long-lived. Final print: `notes/harbor.md  (208 bytes)`. Exit 0.

Warm run, a new process: the capture session called `append_file(path=notes/harbor.md, ..., unique=True)` instead of rewriting, growing the note to 417 bytes, and the recall session answered the locking question again from the store. Final print: `notes/harbor.md  (417 bytes)`. Exit 0.

The byte counts are model-dependent: the note body is written by the model, so sizes vary run to run (this pass observed 208 cold and 417 warm over one cold/warm pair; spec verification observed 211 and 367 for the same script). The invariant is the shape: the cold run writes the note, the warm run appends to it, and the file grows.

Serving run: `python cookbook/examples/second_brain` (the folder's `__main__.py`, which pins cwd to the example folder and serves with reload on), launched from `cookbook/examples/` to exercise the folder/module name collision path. Driven by a `fastmcp.Client` over `StreamableHttpTransport` at `http://localhost:7777/mcp`; no stray `tmp/` appeared outside the example folder:

```
TOOLS: ['get_agentos_config', 'run_agent', 'run_team', 'run_workflow',
        'continue_run', 'cancel_run', 'get_sessions', 'get_session_runs']
run_agent(agent_id=second-brain, message=What did I decide about locking in Harbor?, user_id=ashpreet)
  -> "You chose Postgres advisory locks for Harbor instead of SELECT ... FOR UPDATE
      SKIP LOCKED. The reason was that Harbor workers are long-lived ..."
run_agent(agent_id=second-brain, message=What am I working on?)   # no user_id
  -> the agent reports it has no accessible project notes for this run
```

The no-`user_id` call is the templated namespace failing closed: `brain/{user_id}` cannot resolve, so the tool call fails and the agent says so in prose instead of reading another user's notes. The underlying `InvalidPathError` is caught by the filesystem toolkit and returned to the model as the tool result, so it never appears in the server log; the observable evidence is the agent's answer quoted above.

---
