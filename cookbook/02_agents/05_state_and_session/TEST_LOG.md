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

### shared_session_agents.py

**Status:** PASS
**Tier:** untagged
**Description:** Three agents (Researcher, Skeptic, Writer) share one session with shared_session=True. A broadcast turn runs the same Message through all three; two turns are addressed to one agent with to=; a final turn is broadcast again. Tested 2026-10-25 with gpt-5.6-luna.
**Result:** Completed in about 60s. The Skeptic answers the Researcher by name on turn one, so the labelled replay works. The Writer's context on turn three holds the Skeptic-only exchange and its plan folds that risk in. The stored transcript prints each broadcast turn once with every agent's reply under it.

---
