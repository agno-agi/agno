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
**Description:** `search_compacted_messages=True` with `compacted_token_budget=150` and manual folding, on a fresh
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

### compaction/compaction_token_counter.py

**Status:** PASS
**Description:** Compares three token counters on the same two messages, then runs an agent with `Compaction(compact_at_tokens=1_500, uncompacted_runs=1, use_model_token_count=True)` on `gpt-5.6-luna` over five detailed questions.
**Result:** Every threshold check counted with the model's own `count_tokens` (4995, 8768, 13104, 12119 tokens) with no fallback. The fold happened on the fourth run: `Folded 4 messages (13072 -> 5404 tokens)`. Earlier runs declined because the fold was still under 2x the one-run tail (the fold ratio guard was then on by default; it is now opt-in via `enforce_min_fold_ratio`). `compact_at_tokens=1_500` sits below the size after a fold, so compaction warns that the next run will fold again - expected for a threshold this low.

---

### compaction/compaction_async_token_counter.py

**Status:** PASS
**Description:** Runs an agent with `arun`, `num_history_runs=10` and `Compaction(compact_at_tokens=2_800, uncompacted_runs=1, token_counter=count_with_margin)`, where `count_with_margin` is an async function returning the model's `acount_tokens` plus 10%, on `gpt-5.6-luna`. Each of five turns shares a fixed ~700-token document and asks for a one-word reply, on a fresh session per run.
**Result:** Deterministic across two runs - every size check awaited the async counter with the same counts (716 -> 787, 1430 -> 1573, 2144 -> 2358, 2858 -> 3143). The fifth run crossed the threshold and folded both times: `Folded 6 messages (2816 -> 1070 tokens)` and `(2816 -> 1147 tokens)`; only the summary's length varies. Completed in 18s.

---

### compaction/compaction_threshold_room.py

**Status:** PASS
**Description:** The same six ~700-token turns twice on `gpt-5.6-luna`, with `uncompacted_runs=1` and `compacted_token_budget=300`: first at `compact_at_tokens=1_200`, then at `3_000`.
**Result:** At 1,200 every run folded from run 3 (846-1,010 tokens left after each fold) and compaction warned on each fold that the threshold leaves too little room after the system prompt, tools and summary. At 3,000 the first fold came on run 6 (979 tokens left), with no warning. Completed in 55s.

---
