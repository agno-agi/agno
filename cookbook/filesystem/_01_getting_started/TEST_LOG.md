# Test Log - _01_getting_started

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.0 (source tree, branch feat/agent-fs).
Re-run fresh at the final sweep (same date): every file in this folder PASS.

### basic.py

**Status:** PASS

**Description:** Durability across processes: two separate invocations of the same file share one SQLite store; run 1 records a decision, run 2 detects the populated store and recalls it.

**Result:** Run 1 printed "run 1 of 2: store is empty - asking the agent to record a decision"; the agent called `append_file(path=notes/decisions.md, content=Use SQLite for local development and Postgres in production.)` and replied "Recorded in `notes/decisions.md`." Run 2 (fresh process) printed "run 2 of 2: store already populated - asking the agent to recall" and answered "We decided to use **SQLite** for local development." Notable: an earlier draft asked the agent to store a user preference and gpt-5.5 refused, citing its instructions that user facts belong in memory, not its private filesystem — the D8 instruction boundary enforcing itself.

---

### standalone.py

**Status:** PASS

**Description:** The programmatic API with no Agent import and no API keys: write, read, append, exact-line membership via contains(), list, usage.

**Result:** Config read back verbatim ("focus: AI infrastructure / audience: engineers"). First membership check returned `{'found': ['https://example.com/a'], 'missing': ['https://example.com/c']}`; after appending the missing record the second check returned `{'found': ['https://example.com/c'], 'missing': []}`. Final listing `['notes/config.md', 'seen/2026-07-24.md']`, usage `{'files': 2, 'bytes': 111}`.

---

### local_backend.py

**Status:** PASS

**Description:** Same agent code over LocalFileSystem instead of DbFileSystem; prints the real on-disk tree afterwards.

**Result:** Agent wrote its own working note to `notes/summary.md` (the onboarding-doc summary) and appended `https://example.com/a` to `seen/2026-07-24.md`, replied "Recorded both items." On-disk tree printed under `tmp/agent_fs_local_<uuid>`: `getting-started/notes/summary.md` and `getting-started/seen/2026-07-24.md`. Both are the agent's own records, not user facts.

---
