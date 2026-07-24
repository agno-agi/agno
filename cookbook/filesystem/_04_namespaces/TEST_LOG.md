# Test Log - _04_namespaces

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.1 (source tree, branch feat/agent-fs at 7df2fad3a).
Re-run fresh at the final sweep (same date): every file in this folder PASS.
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased rather than quoted.

### basic.py

**Status:** PASS

**Description:** One static agent with namespace="assistant/{user_id}": alice and bob each get an isolated work-log of what the agent did for them, alice's recall returns only her log, and an anonymous run (no user_id) fails closed.

**Result:** Alice's recall called `list_files(directory=., ...)` then `read_file(path=work-log.md, ...)` and returned only her own entry, with nothing of bob's. On the anonymous run all eight tools stayed registered and callable; each *call* errored, so the two `list_files` attempts both came back with the fail-closed error and the agent reported it had no user_id and could not reach its files. Backend proof printed both isolated namespaces: `assistant/alice -> 'Resolved a duplicate-charge refund on the checkout service.\n'` and `assistant/bob   -> 'Investigated a failed invoice on the billing service.\n'`.

---

### custom_factory.py

**Status:** PASS

**Description:** A callable tool factory picks the namespace per run from run_context (VIP tiering): alice lands in support/vip/alice, carol in support/standard/carol. The factory result is cached per user_id by agno's callable-tools cache.

**Result:** Both runs recorded their case note and the direct backend read showed the factory's routing: `support/vip/alice      -> 'alice reported a login issue.\n'` and `support/standard/carol -> 'carol asked about invoices.\n'`. Each namespace held only its own note. Whether the model prefixes a date to the note varies between runs and is not part of what this example demonstrates.

---

### shared_namespace.py

**Status:** PASS

**Description:** A recorder agent with the full surface and an answering agent on tools(read_only=True) share the namespace research/decisions by name; the consumer must be able to read but hold no write tool.

**Result:** Consumer tool surface printed exactly `['read_file', 'list_files', 'search_content', 'check_lines']`, with no write, append, move or delete. The recorder appended both decisions in one `append_file` call. The consumer answered via `list_files(directory=., ...)` then `read_file(path=decisions/2026-07.md, ...)`, finding the file without being told its path, and reported pgvector as approved for production. Note that read_only constrains the tool surface only: the same FileSystem object still exposes `write()` from Python.

---
