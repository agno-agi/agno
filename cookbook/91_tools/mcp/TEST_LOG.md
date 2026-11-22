# Test Log

### battle_training.py

**Status:** PASS

**Description:** Connects to battle.training's production Streamable HTTP MCP endpoint through Agno's `MCPTools`. Without a key it registers only the 12 public read tools (via `include_tools`); with `BATTLE_TRAINING_API_KEY` set it sends the key as a bearer header and also registers the 5 write tools. The check calls tools directly through the MCP session, because this environment has no OpenAI API key for a full agent loop.

**Result:** Keyless run registered exactly the 12 read tools; `get_ladder` returned the 396-bot Armor ladder (top: daemon-amber, rating 2704), `get_bot` returned delynn-prime (Armor rank 393/396, rating 671, RD 86, 5W-10L-5D) and delynn-pyong (Air rank 4/8, rating 1441, RD 62, 8W-10L-13D), and `list_ladders` returned the running ladders and cups. The keyed run registered 17 tools, and `whoami` over the bearer header returned the account and its two bots. The example also passes Python compilation and Ruff format and lint checks (Agno 3.2.1, Python 3.12).

---

### getyoutubetranscript.py

**Status:** NOT RUN

**Description:** Connects to GetYouTubeTranscript's production Streamable HTTP MCP endpoint through Agno's `MCPTools` with bearer authentication and runs a research task with OpenAI.

**Result:** Not run end to end through Agno. Checked directly against the endpoint: `initialize` and `tools/list` succeed and list 13 tools (`get_youtube_transcript`, `search_youtube`, channel and playlist tools, `get_credits`); a `tools/call` with an invalid bearer token returns HTTP 401, and one without a token returns `invalid_token`. The example passes Python compilation; Ruff was not run.

---

### magic_hour.py

**Status:** PASS

**Description:** Connects to Magic Hour's production Streamable HTTP MCP endpoint through Agno's `MCPTools` with bearer authentication and discovers the available media-generation and project workflow tools. The check uses an invalid test token so it cannot create a billable project.

**Result:** MCP initialization completed, Agno discovered 44 tools, and `ping` returned `pong`. The authenticated `account_retrieve` tool rejected the invalid token with HTTP 401, so the check could not create a billable project. The example also passes Python compilation, Ruff formatting, and Ruff lint checks. A paid end-to-end generation remains intentionally untested until a reviewer credential is provided securely.

---

### peer_cash.py

**Status:** PASS

**Description:** Uses Agno 2.9.0 `MCPTools` to launch `peer-cash-mcp@0.1.2` over stdio with the same command as the cookbook, completes MCP initialization, and calls the live production capabilities tool.

**Result:** Agno discovered all nine tools and `peer_cash_capabilities` returned the Base 8453 USDC destination plus the live payout catalog. A regression check also parsed all nine MCP tools with the cookbook's structured output enabled and confirmed that `peer_cash_prepare` is no longer marked strict, avoiding OpenAI's incompatible strict-schema rewrite. The example passes Python compilation and Ruff checks.

---

### structured_content.py

**Status:** PASS

**Description:** Connects to the hosted DeepWiki MCP server (public, no auth) and asks
about facebook/react. Verifies the agent answers from the tool's `structuredContent`
and that `structured_content_hook` reads the typed object from
`ToolResult.metadata["structured_content"]`.

**Result:** `ask_question` returned successfully (with `timeout_seconds=60` for DeepWiki's
slower analysis), the hook printed the `structured_content` payload read from metadata, and
the agent produced a grounded one-sentence answer about the repository.

---

### Pending

**Status:** NOT RUN

**Description:** Tests for this cookbook directory have not been executed yet in this workspace.

**Result:** Add individual run results after executing examples.

---

### mem0.py, supabase.py

**Status:** PASS (model only)

**Description:** Moved off `o4-mini`, which OpenAI shut down on 2026-10-23, to `OpenAIResponses(id="gpt-5.6-terra")`. `OpenAIChat` rejects function tools for this model (`use /v1/responses or set reasoning_effort to 'none'`), so both examples switch to `OpenAIResponses`.

**Result:** An async run with a function tool and `ReasoningTools` completes on `OpenAIResponses(id="gpt-5.6-terra")` and errors on `OpenAIChat`.

---

### graphiti.py

**Status:** PASS

**Description:** Moved off `o3-mini` to `OpenAIResponses(id="gpt-5.6-sol")`. Ran against the Graphiti MCP server (`zepai/knowledge-graph-mcp`) on SSE at `localhost:8000/sse`.

**Result:** The agent calls `add_memory`, `get_episodes`, `search_nodes` and `search_memory_facts` and answers.

---
