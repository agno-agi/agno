# Test Log - team_brain

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at 164f9a6c1).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

### test.py

**Status:** PASS

**Description:** The CLI driver: log one decision as alice, ask the librarian what the team has decided, then print the log file itself. There is no token on this path, so the author is passed in directly; over MCP it comes off the token instead.

**Result:** Fresh `tmp/`, exit 0:

```
Logged: - We ship the queue on Postgres, not SQS, because we already run Postgres. (decided by alice)
• read_file(path=decisions.md, start_line=1, end_line=200)
The team has decided:
> "- We ship the queue on Postgres, not SQS, because we already run Postgres. (decided by alice)"
```

The librarian quoted the line with its attribution, as instructed, and the printed `decisions.md` matched it exactly.

### team_brain.py

**Status:** PASS

**Description:** Serving run. `python team_brain.py` from the example folder now mints one token per teammate and serves directly (the folder's `__main__.py` is gone). Driven at `http://localhost:7801/mcp` as alice, then as bob on a different token. Port moved to 7801 for this pass because another AgentOS held 7777.

**Result:** Tokens printed on the way up, and the advertised `remember` schema carries no `user_id` at all:

```
alice token: agno_pat_duXGF96q...
bob token: agno_pat_uDHaeb3k...
TOOLS: ['remember', 'recall']
remember schema args: ['decision']
ALICE remember -> Logged: - Retries use exponential backoff, capped at 30s. (decided by sa:alice)
BOB recall -> The team decided: "Retries use exponential backoff, capped at 30s. (decided by sa:alice)"
```

Attribution (`sa:alice`) comes off the token, not off anything the caller typed, and bob read alice's line back with her name on it, so the store is genuinely shared. Earlier passes on this example also proved that a client sending `user_id` anyway is rejected (`unexpected_keyword_argument`) and that anonymous callers get 401 before reaching any tool; the auth path is unchanged by the entry-point split.

---
