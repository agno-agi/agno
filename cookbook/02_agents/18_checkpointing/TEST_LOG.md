# Checkpointing Cookbook Test Log

Tracks execution status of the checkpointing examples.

## Setup

```bash
./scripts/demo_setup.sh
```

Requires `OPENAI_API_KEY` to be set.

## Examples

### 01_crash_recovery.py

**Status:** Not yet tested

**Description:** Demonstrates `checkpoint="steps"` writing mid-run state to the DB
after each tool batch, and the unified `/continue` accepting any persisted run.

**Expected:** Initial run completes; printed checkpoint marker is non-None; the
follow-up `/continue` call resolves cleanly with status=COMPLETED.

---

### 02_time_travel.py

**Status:** Not yet tested

**Description:** Demonstrates `continue_from="end"` for follow-ups and
`continue_from="last_user"` for rewinding to a symbolic message boundary.

**Expected:** First run answers about Paris. Follow-up from `"end"` and rewind
from `"last_user"` both auto-fork the completed run and preserve the source.

---

### 03_forking.py

**Status:** Not yet tested

**Description:** Demonstrates `fork=true` cloning a run at a checkpoint into a
new sibling within the same session.

**Expected:** Original run answers about Paris. Forked run has a new run_id,
`forked_from_run_id` set, different content. Session contains both runs.

---
