# Test Log — workspace_tools

Tracks ad-hoc runs of the cookbooks in this folder. Update after each test
session. See the parent `cookbook/91_tools/TEST_LOG.md` for the format
convention.

---

### basic_usage.py

**Status:** PASS

**Date:** 2026-04-25

**Description:** Agent reads a tmp README.md, writes NOTES.md with a 2-line
summary, then lists files. Uses `confirm=[]` so all tool calls auto-pass.

**Result:** Agent called `read_file`, `write_file`, and `list_files` in the
expected order. `write_file` returned `Wrote 95 chars to NOTES.md`. Final
message confirmed both files exist. Tool call rendering in the run timeline
showed readable args (e.g. `path=README.md, start_line=1, end_line=200`).

---

### with_confirmation.py

**Status:** PASS

**Date:** 2026-04-25

**Description:** Agent reads a tmp draft.md and edits a typo. Uses default
partitions, so `read_file` auto-passes but `edit_file` pauses for approval.
Smoke-tested with `yes y | python …` to drain confirmation prompts.

**Result:** `read_file` ran silently. `edit_file` paused, surfaced
`tool_name=edit_file` and the proposed `tool_args` (path, old_str, new_str)
through the `active_requirements` API. After confirm, the edit applied:
`taht` → `that`. `requirement.confirm()` and `agent.continue_run(...)`
flow worked as expected.

---
