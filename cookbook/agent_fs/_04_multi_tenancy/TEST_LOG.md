# Test Log - _04_multi_tenancy

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.0 (source tree, branch feat/agent-fs).

### basic.py

**Status:** PASS

**Description:** One static agent with namespace="assistant/{user_id}": alice and bob write to fully isolated stores, alice's recall returns only her note, and an anonymous run (no user_id) fails closed.

**Result:** Alice's recall answered "Your current project is the **checkout service**." (bob's note untouched). The anonymous run reported the tool refusal honestly: "the file tool is unavailable for this run because no `user_id` was provided to the file system". Backend proof printed both namespaces: assistant/alice -> 'This run is about the checkout service.\n', assistant/bob -> 'This run is about the billing service.\n'.

---

### custom_factory.py

**Status:** PASS

**Description:** A callable tool factory picks the namespace per run from run_context (VIP tiering): alice lands in support/vip/alice, carol in support/standard/carol.

**Result:** Both runs recorded their case note; the direct backend read showed the factory's routing: support/vip/alice -> 'alice reported a login issue.\n' and support/standard/carol -> '2026-07-24: carol asked about invoices.\n' (the model added a date prefix to carol's note on its own).

---

### shared_namespace.py

**Status:** PASS

**Description:** A recorder agent with the full surface and an answering agent on tools(read_only=True) share the namespace research/decisions by name; the consumer must be able to read but hold no write tool.

**Result:** Consumer tool surface printed exactly ['read_file', 'list_files', 'search_content', 'check_lines']. The recorder appended both decisions in one append_file call. The consumer's system message carried the read-only instructions variant ("You have read access to a durable filesystem written by another agent"), and it answered via list_files + read_file: "Vector database: pgvector approved for production."

---
