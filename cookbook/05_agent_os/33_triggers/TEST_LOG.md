# Test Log: 33_triggers

Tested 2026-11-25 with `.venv/bin/python` in a worktree of `feat/triggers`
(from main at `bd24f44997`), SQLite, `gpt-5.6-luna`. First tested 2026-11-24;
run again after each round of changes, last with the `triage-labeled` trigger
and the GitHub App credentials added to the file.

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
was called twice, with the status and output of each run. `--events` printed the
five stored events. Serving for a real webhook was not run: `REAL_GITHUB.md`
lists the six checks against GitHub itself, and none of them has been run.

---

### stored_triggers.py

**Status:** PASS

**Description:** Run with `--check` on 2026-11-25. The app is served in the same
process on port 7792 with its real startup, with a GitHub source and no trigger
in code. Over HTTP: the sources are listed; a signed issue is delivered before
any trigger exists; a trigger is created with `POST /triggers`; a trigger on a
source that is not declared is tried; the issue is delivered again; its event is
replayed. Then an agent with `TriggerTools` is asked, in a real run on
`gpt-5.6-luna`, to set up a trigger for new pull requests, and that trigger is
disabled and deleted over REST.

**Result:** The first delivery was stored as ignored with the reason that no
trigger listens. The trigger on the undeclared source was refused with 422. The
second delivery started a run that ended as success, and the replay was a second
event with a run of its own in the same session. The agent created
`review-pull-requests` for `pull_request.opened` aimed at the triage agent.
Serving for a real webhook was not run.

---
