# Test Log: cookbook/91_tools/renor

## Latest Verification — 2026-11-09

**Environment:** Python 3.12.4, `agno 3.1.12`, `mcp 2.3.0`, `fastmcp 4.1.6`,
`renor-engine 1.4.6`, Node.js 25.8.2 on Windows 11.

**Model:** not invoked. The verification host had no `OPENAI_API_KEY`, so the
model call path was not exercised; `create_agent()` construction and every MCP
tool call were verified directly.

**Pre-flight:** `python cookbook/scripts/check_cookbook_pattern.py --base-dir
cookbook/91_tools/renor --recursive` checked 1 file with 0 violations.
`ruff check cookbook/91_tools/renor` passed with no findings.

---

### agent_memory.py

**Status:** PASS

**Description:** Two separate processes ran the recipe's `create_agent()` and
MCP wiring against one vault (`tmp/renor-vault-smoke`). Process 1 called
`remember_fact`; process 2 called `search` and `facts`.

**Result:** The server exposed `entity`, `evidence`, `facts`, `keyword`, `note`,
`remember_fact`, `search`, and `status`, and the recipe handed the tool object to
`Agent(tools=...)`. Process 1 stored `Acme Corp`, `enterprise_billing_cycle`,
`annual billing starting Q1 2026` (event `MEM_MW8YBXFE57WU41`) and created
`System/Memory Events Ledger.md`. Process 2, which shared no in-memory state with
the first, returned `"text": "Acme Corp / enterprise_billing_cycle: annual billing
starting Q1 2026"` from `search` plus the matching row from `facts`. Recall therefore
reads the vault on disk, not the conversation.

**Notes:** On Windows, `MCPTools` spawns `npx` with `Command::new`, which does not
resolve `npx.cmd`; the smoke run launched the engine entry script with `node.exe`
instead. The recipe keeps `npx -y renor-engine mcp` as the issue requests, which is
the command that works on macOS and Linux.

### Not exercised: the agent decision loop

**Status:** NOT RUN

**Description:** The point of the recipe is an agent that decides on its own to
call `remember_fact` and later recalls what it stored. That needs a model call
(`OPENAI_API_KEY`), which the verification host did not have. The smoke run above
exercises the same tools against the same on-disk vault, but calls them directly
instead of letting the agent choose them.

**How to close the gap:** with `OPENAI_API_KEY` set, run the recipe twice:

```text
python cookbook/91_tools/renor/agent_memory.py
python cookbook/91_tools/renor/agent_memory.py
```

**Result:** not executed here. On success, the first run reports the stored
subject/predicate/object and the second answers from the vault written by the
first.

---
