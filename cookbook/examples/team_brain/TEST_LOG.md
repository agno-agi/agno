# Test Log - team_brain

Tested 2026-07-25 against `gpt-5.5` (OpenAIResponses), agno 2.8.2 (source tree at a1aad6e5a).
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased.

### team_brain.py

**Status:** PASS (server example: it serves until stopped, so the folder-wide runner sweep cannot complete it; verified manually with two real `fastmcp.Client` sessions on different tokens)

**Description:** Token-attributed team decision log. Booted the server from this folder (fresh `tmp/`), took the two tokens it printed, then drove `http://localhost:7777/mcp` as alice, as bob, and anonymously. Attempted to spoof `user_id` from the client.

**Result:** The advertised schemas carry no `user_id` parameter at all:

```
TOOL remember {"additionalProperties": false, "properties": {"decision": {"type": "string"}}, "required": ["decision"], "type": "object"}
TOOL recall {"additionalProperties": false, "properties": {"question": {"type": "string"}}, "required": ["question"], "type": "object"}
```

The four proofs, from the driver session (markdown bold and curly quotes stripped; identifiers, attributions and error text unchanged):

```
ALICE remember -> Logged: - we ship the pricing page on Friday (decided by sa:alice)
ALICE spoof REJECTED -> ToolError 1 validation error for call[remember]
  user_id
    Unexpected keyword argument [type=unexpected_keyword_argument, input_value='sa:bob', input_type=str]
BOB remember -> Logged: - we drop the legacy CSV export (decided by sa:bob)
BOB recall -> We ship the pricing page on Friday - decided by sa:alice.
  > "we ship the pricing page on Friday (decided by sa:alice)"
ANON -> HTTPStatusError Client error '401 Unauthorized' for url 'http://localhost:7777/mcp'
```

Four things proven: `user_id` is absent from the schema the client sees; attribution (`sa:alice`, `sa:bob`) comes off the token, not off anything the caller typed; a client that sends `user_id` anyway is rejected rather than believed; anonymous callers get 401 before reaching any tool. Bob's `recall` read alice's line back with her attribution, so the store is genuinely shared.

---
