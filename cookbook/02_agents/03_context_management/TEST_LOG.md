# Test Log -- 03_context_management

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### compaction.py

**Status:** PASS
**Tier:** untagged
**Description:** Compaction with `compaction=Compaction(compact_at_runs=5, keep_last_runs=2)` over an
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
**Description:** `searchable=True` with the default summarization prompt (no artificial lossiness).
Plants unguessable values (ticket KR-4417-QX, a 47-day window, build hash b7f2ae91c4), buries them
under five unrelated turns, then asks for them back. Sets `min_chars_to_reclaim=500` because the
demo turns are short; the default suits real sessions.
**Result:** Completed successfully. 2 compactions; the final turn shows `read_file` and
`search_content` calls against the archive before answering with both exact values. Confirmed the
summarizer emits its "Not covered here:" line, and that the summary message only promises a lookup
when `searchable=True`.

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
