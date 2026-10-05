# Test Log -- 03_context_management

> Note: entries below predate the removal of `compact_at_runs` / `compact_at_messages`.
> Compaction now triggers on `compact_at_tokens` only, or on an explicit `agent.compact()`.
> The configurations quoted here no longer construct; the observations still stand.


**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### compaction/compaction_with_tools.py

**Status:** PASS
**Description:** Folding a transcript containing tool calls. Four calculator calls across five
turns, then a question that spans them.
**Result:** 12 messages folded, 1014 -> 471 tokens. All 4 assistant tool-call turns and 4 tool
results still stored (23 messages total).

---

### compaction/compaction_anthropic.py

**Status:** PASS
**Description:** The same folding on `claude-sonnet-4-5`. Anthropic carries history in the
request rather than by id, so there is no server-side chain for compaction to sever.
**Result:** 6 messages folded, 24602 -> 7732 tokens (69% smaller).

---

### compaction/compaction_anthropic_thinking.py

**Status:** PASS
**Description:** Extended thinking (`budget_tokens=1024`) plus calculator tools - an assistant
turn is then a thinking block, a tool call, and its result, all of which must stay together.
**Result:** 18 messages folded, 7858 -> 1621 tokens (79% smaller). 15 thinking blocks preserved
in storage; no signature or pairing errors.

---

### compaction.py

**Status:** PASS
**Tier:** untagged
**Description:** Compaction with `compaction=Compaction(compact_at_runs=5, uncompacted_runs=2)` over an
8-turn session. Verified the compaction fired, the summary replaced the older turns, and the agent
still answered "remind me what my budget was" correctly from a turn that had been compacted away.
**Result:** Completed successfully. 6 messages replaced by the summary, all 16 still stored in the
session, archived at `0001.md`.

---

### compaction_thresholds.py

**Status:** PASS
**Tier:** untagged
**Description:** Token-based threshold (`compact_at_tokens=100_000`) with a cheaper summarization
model. Two short runs stayed well under the threshold.
**Result:** Completed successfully. 0 compactions, as expected for a short session.

---

### compaction_searchable_archive.py

**Status:** PASS
**Tier:** untagged
**Description:** `searchable=True` with `summary_budget_tokens=150` and manual folding, on a fresh
session per run. Shares a 30-row parts list, folds it away - no 150-token summary can carry 30 rows -
then asks for the lot number of part 23 with `print_response`, so the tool call is visible.
**Result:** 6 of 6 live runs on `gpt-5.6-luna` folded, called `search_compacted_history` (e.g.
`pattern=part 23|23|lot`, shown in the Tool Calls panel) and answered with the correct lot number,
82137. The earlier version planted three short values a summary could keep, so the final question
was often answered from the summary with no search, and reused a fixed session id across runs.

---

### compaction_events.py

**Status:** PASS
**Tier:** untagged
**Description:** Streams `CompactionStarted` / `CompactionCompleted` over six long-answer turns and
prints the token reduction each compaction achieved.
**Result:** Completed successfully. 3 compactions, reducing context by 44.6%, 55.4% and 40.7%
(for example 16787 -> 9296 tokens), each archived to its own file.

---

### compaction_async.py

**Status:** PASS
**Tier:** untagged
**Description:** Compaction on the async path via `aprint_response`.
**Result:** Completed successfully. 1 compaction.

---

### compaction_local_archive.py

**Status:** PASS
**Tier:** untagged
**Description:** `fs=LocalFileSystem(root="tmp/compaction_archive")` writes the archive to disk as
markdown instead of into the database.
**Result:** Completed successfully. Wrote a readable `0001.md` under a per-session directory.

---

### few_shot_learning.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates few shot learning. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### filter_tool_calls_from_history.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates filter tool calls from history. Ran successfully and produced expected output.
**Result:** Completed successfully in 39s.

---

### instructions.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates instructions. Ran successfully and produced expected output.
**Result:** Completed successfully in 2s.

---

### instructions_with_state.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates instructions with state. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### introduction_message.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates introduction message. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---

### system_message.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates system message. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---
