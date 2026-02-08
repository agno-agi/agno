# Test Log: run_control

> Updated: 2026-02-08 00:52:28 

## Pattern Check

**Status:** PASS

**Result:** Checked 4 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/run_control. Violations: 0

---

### cancel_run.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/run_control/cancel_run.py`.

**Result:** Completed successfully (exit 0) in 35.54s. Tail: Content Preview: Once upon a time in the vast, enchanted realm of Auroria—a land where magic and modernity coexisted—there lived a dragon named Zephyr. Zephyr was no ordinary dragon. His scales shimmered in hues of tw... | WARNING: Team run completed before cancellation | Team cancellation example completed!

---

### model_inheritance.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/run_control/model_inheritance.py`.

**Result:** Completed successfully (exit 0) in 26.49s. Tail: ┃ content is suitable for publication.                                         ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---

### remote_team.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/run_control/remote_team.py`.

**Result:** Exited with code 1 in 0.45s. Tail: File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/client/os.py", line 201, in _arequest | raise RemoteServerUnavailableError( | agno.exceptions.RemoteServerUnavailableError: Failed to connect to remote server at http://localhost:7778

---

### retries.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/run_control/retries.py`.

**Result:** Completed successfully (exit 0) in 12.32s. Tail: ┃ technology in our lives.                                                     ┃ | ┃                                                                              ┃ | ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

---
