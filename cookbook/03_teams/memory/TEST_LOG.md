# Test Log: memory

> Updated: 2026-02-08 15:49:52

## Pattern Check

**Status:** PASS

**Result:** Checked 3 file(s) in /Users/ab/conductor/workspaces/agno/colombo/cookbook/03_teams/memory. Violations: 0

---

### 01_team_with_memory_manager.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/memory/01_team_with_memory_manager.py`.

**Result:** Executed successfully. Duration: 7.16s. Tail: /postgres.py", line 1093, in upsert_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/postgres/postgres.py", line 1050, in upsert_session |     return TeamSession.from_dict(session_dict) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---

### 02_team_with_agentic_memory.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/memory/02_team_with_agentic_memory.py`.

**Result:** Executed successfully. Duration: 17.59s. Tail: /postgres.py", line 1093, in upsert_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/postgres/postgres.py", line 1050, in upsert_session |     return TeamSession.from_dict(session_dict) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---

### learning_machine.py

**Status:** PASS

**Description:** Executed `.venvs/demo/bin/python cookbook/03_teams/memory/learning_machine.py`.

**Result:** Executed successfully. Duration: 4.98s. Tail: db/sqlite/sqlite.py", line 1039, in upsert_session |     raise e |   File "/Users/ab/conductor/workspaces/agno/colombo/libs/agno/agno/db/sqlite/sqlite.py", line 998, in upsert_session |     return TeamSession.from_dict(session_raw) |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ | NameError: name 'requirements' is not defined. Did you mean: 'RunRequirement'?

---
