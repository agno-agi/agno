# Test Log: state

> Updated: 2026-02-08 15:49:52

## Pattern Check

**Status:** PASS

**Result:** Checked 5 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/state. Violations: 0

---

### agentic_session_state.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/state/agentic_session_state.py`.

**Result:** Exited with code 1. Tail: ession_state |     return get_session_state_util(cast(Any, team), session_id=session_id) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/utils/agent.py", line 760, in get_session_state_util |     raise Exception("Session not found") | Exception: Session not found

---

### change_state_on_run.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/state/change_state_on_run.py`.

**Result:** Executed successfully. Duration: 6.42s. Tail: , line 314, in upsert_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/in_memory/in_memory_db.py", line 308, in upsert_session |     return TeamSession.from_dict(session_dict_copy) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---

### nested_shared_state.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/state/nested_shared_state.py`.

**Result:** Exited with code 1. Tail: ession_state |     return get_session_state_util(cast(Any, team), session_id=session_id) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/utils/agent.py", line 760, in get_session_state_util |     raise Exception("Session not found") | Exception: Session not found

---

### overwrite_stored_session_state.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/state/overwrite_stored_session_state.py`.

**Result:** Exited with code 1. Tail: ession_state |     return get_session_state_util(cast(Any, team), session_id=session_id) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/utils/agent.py", line 760, in get_session_state_util |     raise Exception("Session not found") | Exception: Session not found

---

### state_sharing.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/state/state_sharing.py`.

**Result:** Executed successfully. Duration: 54.48s. Tail: db/sqlite/sqlite.py", line 1039, in upsert_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/sqlite/sqlite.py", line 998, in upsert_session |     return TeamSession.from_dict(session_raw) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---
