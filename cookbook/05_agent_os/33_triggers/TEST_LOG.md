# Test Log: 33_triggers

Tested 2026-11-25 with `.venv/bin/python` in a worktree of `feat/triggers`
(from main at `bd24f44997`), SQLite, `gpt-5.6-luna`. First tested 2026-11-24;
run again after the fixes to how an event's run is followed and to which
AgentOS a trigger belongs.

### github_issues.py

**Status:** PASS

**Description:** Run with `--check`. The app is served in the same process on
port 7791 with its real startup, so the trigger poller and the scheduler both
run. Seven signed deliveries are sent over HTTP: an issue opened by a member, the
same delivery again, a reply on that issue by a collaborator, an issue from an
account with no association, an issue for another repository, an issue with no
description, and one signed with the wrong secret.

**Result:** 2 of 7 deliveries started a run, and both ran in one session: the
issue and the reply on it. The redelivery was answered as a duplicate and
started nothing. The outside account and the other repository were stored as
ignored with their reasons. The empty issue was stored as skipped by `prepare`.
The bad signature was answered 403 and nothing was stored for it. `on_complete`
was called twice, with the status and output of each run. Serving for a real
webhook was not run.

---
