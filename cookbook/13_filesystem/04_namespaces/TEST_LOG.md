# Test Log - 04_namespaces

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.1 (source tree, branch feat/agent-fs at 7df2fad3a).
Re-run fresh at the final sweep (same date): every file in this folder PASS.
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased rather than quoted.


### Re-run 2026-07-25 — instructions composed explicitly

`fs.tools()` no longer adds its instructions to the system prompt; every agent in this
folder now passes `fs.instructions()` in its own instructions list. Re-tested against
`gpt-5.5` (OpenAIResponses), agno 2.8.2 source tree, branch fix/filesystem-explicit-instructions.

**shared_namespace.py — PASS.** Consumer tool surface printed `['read_file', 'list_files', 'search_content', 'check_lines']`. The recorder appended both decisions to `decisions/2026-07.md`; the read-only answerer, carrying `consumer_fs.instructions(read_only=True)`, called `list_files` then `read_file(path=decisions/2026-07.md, start_line=1, end_line=200)` and quoted the pgvector decision with its source line.

---

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

## 2026-07-26 — corrections after the default flip

`read_only=True` is now three tools, not four: `check_lines` left every default
set and is reachable only through `include_tools`. Both entries above record a
consumer surface of `['read_file', 'list_files', 'search_content', 'check_lines']`,
which is what the pre-flip code printed; `shared_namespace.py` itself was updated
and says "three read tools". Re-verified against the current code:
`FileSystem(db, namespace=...).tools(read_only=True)` yields exactly
`['read_file', 'list_files', 'search_content']`.
