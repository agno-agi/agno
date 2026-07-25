# Team Brain

One MCP endpoint the whole team points their AI apps at: everyone writes decisions into the same log and reads them back out, and every entry is attributed to the token that wrote it.

## The claim

A chat app cannot do this because the caller cannot type who they are. The author of every decision is taken from the token the client authenticated with.

To be fair about what you can do without this: a shared Notion, or a team wiki behind an MCP server, gets you a shared store, and for reading that is most of the value. What it does not get you is attribution the caller cannot forge. Here `user_id` is not even in the tool schema the client sees; it is filled in server-side from the authenticated token, and a client that sends it anyway is rejected.

## Run it

From the repo root, with `OPENAI_API_KEY` set (the only key needed):

Serve it by running the folder (the `__main__.py` pins the working directory to the example folder, so this works from the repo root or anywhere else):

```bash
.venvs/demo/bin/python cookbook/examples/team_brain
```

Every serve mints fresh tokens for `alice` and `bob` (revoking the previous ones) and prints them before listening:

```
alice token: agno_pat_...
bob token: agno_pat_...
MCP endpoint: http://localhost:7777/mcp (send a token as a bearer header)
```

Running the file directly instead asks the librarian what the log says. On a fresh store it honestly answers that nothing has been decided; after a serving session it quotes the log with attribution (observed: both decisions below, each with its `decided by` line).

## What you will see

Driving the endpoint with two MCP clients on different tokens, and once with no token, observed live (condensed; markdown formatting stripped, nothing else changed):

```
TOOL remember {"properties": {"decision": {"type": "string"}}, "required": ["decision"], ...}
TOOL recall   {"properties": {"question": {"type": "string"}}, "required": ["question"], ...}
ALICE remember -> Logged: - we ship the pricing page on Friday (decided by sa:alice)
ALICE spoof REJECTED -> ToolError 1 validation error for call[remember]
  user_id  Unexpected keyword argument
BOB remember -> Logged: - we drop the legacy CSV export (decided by sa:bob)
BOB recall -> We ship the pricing page on Friday - decided by sa:alice.
ANON -> 401 Unauthorized
```

Four proofs in one session: the schema carries no `user_id`; attribution (`sa:alice`, `sa:bob`) comes off the token; a spoof attempt is rejected rather than believed; anonymous callers never reach a tool.

## Point an MCP client at it

The endpoint is `http://localhost:7777/mcp`, with a token as a bearer header. Client config:

```json
{
  "mcpServers": {
    "team-brain": {
      "url": "http://localhost:7777/mcp",
      "headers": {
        "Authorization": "Bearer agno_pat_..."
      }
    }
  }
}
```

Two tools are exposed, verified live: `remember(decision)` and `recall(question)`.

The `settings=AgnoAPISettings(os_security_key=...)` line in the file is load-bearing: it is what turns authentication on for `/mcp`. Without it every caller's `user_id` is `None` and the attribution claim is false. Do not remove it.

## For production

Swap `SqliteDb(db_file="tmp/team_brain.db")` for `PostgresDb(db_url=...)`; the decision log, sessions and service accounts all move with it. Mint one token per teammate through your own onboarding path instead of reprinting them at boot, keep the `os_security_key` value secret (treat it as an admin credential, not a teammate login), and hand out only `agno_pat_` tokens.

## Known limits

- The security key itself is an unattributed bearer: presenting it authenticates but yields no `user_id`, which is exactly why `remember` refuses `user_id is None` callers instead of logging unattributed decisions.
- `/mcp` has no scope mapping for custom tools, so per-tool authorization lives in the tool body (as `remember`'s guard does here).
- Tokens are reissued on every run and the previous ones revoked. Plaintext cannot be recovered after minting; if a token is lost, mint a new one.
