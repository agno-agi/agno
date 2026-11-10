# Test Log -- 05_state_and_session

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### agentic_session_state.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates agentic session state. Ran successfully and produced expected output.
**Result:** Completed successfully in 20s.

---

### chat_history.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates chat history. Ran successfully and produced expected output.
**Result:** Completed successfully in 19s.

---

### dynamic_session_state.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates dynamic session state. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---

### last_n_session_messages.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates last n session messages. Failed due to missing dependency: ModuleNotFoundError: No module named 'aiosqlite'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---

### persistent_session.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates persistent session. Ran successfully and produced expected output.
**Result:** Completed successfully in 17s.

---

### session_options.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session options. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### session_state_advanced.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session state advanced. Ran successfully and produced expected output.
**Result:** Completed successfully in 32s.

---

### session_state_basic.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session state basic. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### session_state_events.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session state events. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### session_state_manual_update.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session state manual update. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### session_state_multiple_users.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session state multiple users. Ran successfully and produced expected output.
**Result:** Completed successfully in 32s.

---

### session_summary.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates session summary. Ran successfully and produced expected output.
**Result:** Completed successfully in 23s.

---

### search_past_sessions_by_topic.py

**Status:** PASS
**Tier:** untagged
**Description:** Seeds a billing-export session (two runs) and an onboarding session, then asks the agent to recall by topic and to read only the end of a session. Tested 2026-11-10 with .venvs/demo/bin/python and gpt-5.6-luna, without session summaries. The agent called `search_past_sessions(query="IAM role")`, which matched the conversation itself, and answered with what was suspected. It then called `read_past_session(start=-1, num_runs=1)` and quoted only the last question.
**Result:** Completed successfully.

---
