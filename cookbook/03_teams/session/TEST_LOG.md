# Test Log: session

> Updated: 2026-02-12

## Pattern Check

**Status:** PASS

**Result:** Checked 6 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/session. Violations: 0

---

### chat_history.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/session/chat_history.py`.

**Result:** Exited with code 1. Tail: no/colombo/libs/agno/agno/team/team.py", line 2482, in get_session_messages |     return _storage.get_session_messages( |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/team/_storage.py", line 1601, in get_session_messages |     raise Exception("Session not found") | Exception: Session not found

---

### persistent_session.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/session/persistent_session.py`.

**Result:** Executed successfully. Duration: 29.48s. Tail: /postgres.py", line 1093, in upsert_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/postgres/postgres.py", line 1050, in upsert_session |     return TeamSession.from_dict(session_dict) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---

### search_session_history.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/session/search_session_history.py`.

**Result:** Exited with code 1. Tail: dbapi_meth(**dbapi_args) |             ^^^^^^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/.venvs/demo/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 449, in import_dbapi |     __import__("aiosqlite"), __import__("sqlite3") |     ^^^^^^^^^^^^^^^^^^^^^^^ | ModuleNotFoundError: No module named 'aiosqlite'

---

### session_options.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/session/session_options.py`.

**Result:** Exited with code 1. Tail: ^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/team/_storage.py", line 1386, in set_session_name |     set_session_name_util( |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/utils/agent.py", line 685, in set_session_name_util |     raise Exception("No session found") | Exception: No session found

---

### session_summary.py

**Status:** FAIL

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/session/session_summary.py`.

**Result:** Exited with code 1. Tail: session_summary(self, session_id=session_id) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/team/_storage.py", line 1729, in aget_session_summary |     raise Exception(f"Session {session_id} not found") | Exception: Session async_team_session_summary not found

---

### share_session_with_agent.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/session/share_session_with_agent.py`.

**Result:** Executed successfully. Duration: 10.59s. Tail: .py", line 145, in get_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/in_memory/in_memory_db.py", line 132, in get_session |     return AgentSession.from_dict(session_data_copy) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---
