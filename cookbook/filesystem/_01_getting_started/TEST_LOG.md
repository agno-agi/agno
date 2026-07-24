# Test Log - _01_getting_started

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.1 (source tree, branch feat/agent-fs at 7df2fad3a).
Re-run fresh at the final sweep (same date): every file in this folder PASS.
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased rather than quoted.

### basic.py

**Status:** PASS

**Description:** Durability across processes: two separate invocations of the same file share one SQLite store; run 1 records a decision, run 2 detects the populated store and recalls it.

**Result:** After deleting `tmp/filesystem/getting_started.db`, run 1 printed "run 1 of 2: the store is empty, so ask the agent to record a decision" and called `append_file(path=notes/decisions.md, content=2026-07-24: Use SQLite for local development and Postgres in production.)`. Run 2, a separate process, printed "run 2 of 2: the store is populated, so ask the agent to recall", called `list_files(directory=., pattern=, recursive=True, max_depth=3)` then `read_file(path=notes/decisions.md, start_line=1, end_line=20)`, and answered SQLite. The run-2 prompt states no answer, so the recall came from the file. Notable: an earlier draft asked the agent to store a user preference and gpt-5.5 refused, citing its instructions that user facts belong in memory, not its private filesystem, which is the D8 instruction boundary enforcing itself.

---

### standalone.py

**Status:** PASS

**Description:** The programmatic API with no Agent import and no API keys: write, read, append, exact-line membership via contains(), list, usage.

**Result:** Config read back verbatim ("focus: AI infrastructure / audience: engineers"). First membership check returned `{'found': ['https://example.com/a'], 'missing': ['https://example.com/c']}`; after appending the missing record the second check returned `{'found': ['https://example.com/c'], 'missing': []}`. Final listing `['notes/config.md', 'seen/2026-07-24.md']`, usage `{'files': 2, 'bytes': 111}`.

---

### local_backend.py

**Status:** PASS

**Description:** Same agent code over LocalFileSystem instead of a database; prints the real on-disk tree afterwards.

**Result:** The agent called `write_file(path=notes/summary.md, content=Summarized the onboarding doc; the migration timeline is the key risk to flag, overwrite=True)` and `append_file(path=seen/2026-07-24.md, content=https://example.com/a)`. On-disk tree printed under `tmp/agent_fs_local_<uuid>`: `default/notes/summary.md` and `default/seen/2026-07-24.md`. The `default/` prefix is the default namespace, since this file names none. Both files land at mode 0600; before the append-path fix in `libs/agno/agno/fs/local.py` the appended file was 0644.

---
