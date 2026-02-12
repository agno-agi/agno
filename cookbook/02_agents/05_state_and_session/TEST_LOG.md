# TEST LOG

Generated: 2026-02-12 UTC

Pattern Check: Checked 12 file(s) in cookbook/02_agents/05_state_and_session. Violations: 0

### session_state_basic.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### session_state_advanced.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### agentic_session_state.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### dynamic_session_state.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### session_state_events.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### session_state_manual_update.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### session_state_multiple_users.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### chat_history.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### last_n_session_messages.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### persistent_session.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### session_options.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### session_summary.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

Pattern Check: Checked 5 file(s) in cookbook/02_agents/session. Violations: 0

Requires: pgvector (`./cookbook/scripts/run_pgvector.sh`)

### persistent_session.py

**Status:** PASS

**Description:** Persistent session storage with PostgreSQL. Runs 2 queries across same session to demonstrate history in context.

**Result:** Completed successfully. Agent maintained context across runs (knew previous topic about space discoveries).

---

### session_summary.py

**Status:** PASS

**Description:** Automatic session summarization with `enable_session_summaries=True`. Runs multiple conversations then prints SessionSummary.

**Result:** Completed successfully. Summary correctly captured topics (Basketball, Hiking, Locations, New York) and generated a coherent summary.

---

### last_n_session_messages.py

**Status:** PASS

**Description:** Multi-user session history using `AsyncSqliteDb`. Creates multiple sessions per user, then queries history across sessions using `last_n_history_runs`.

**Result:** Completed successfully. Agent correctly recalled topics from previous sessions (currency of Japan, population of India). Previous FAIL due to missing greenlet dependency is now resolved.

---

### session_options.py

**Status:** PASS

**Description:** Demonstrates `store_history_messages=False` — agent uses history during execution but doesn't persist it.

**Result:** Completed successfully. Showed 2 messages stored but 0 history messages (scrubbed), confirming the agent used history during execution but didn't persist it.

---

### chat_history.py

**Status:** PASS

**Description:** Retrieves and displays chat history via `get_chat_history()` method with PostgreSQL.

**Result:** Completed successfully. Chat history retrieved and displayed correctly.

---

---

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

Pattern Check: Checked 7 file(s) in cookbook/02_agents/state. Violations: 0

### session_state_basic.py

**Status:** PASS

**Description:** Basic session state management with `add_to_shopping_list` tool. Uses SqliteDb and instruction interpolation `{shopping_list}`.

**Result:** Completed successfully. Shopping list populated with milk, eggs, bread. Session state correctly persisted.

---

### session_state_advanced.py

**Status:** PASS

**Description:** Advanced state with add_item, remove_item, list_items tools and case-insensitive search. Uses `o3-mini`.

**Result:** Completed successfully. Multi-step add/remove operations worked. Session state reflected final list.

---

### session_state_events.py

**Status:** PASS

**Description:** Demonstrates `stream_events=True` and `RunCompletedEvent` to access session state after run.

**Result:** Completed successfully. Event stream captured correctly. Final session state: `{'shopping_list': ['milk', 'eggs', 'bread']}`.

---

### session_state_manual_update.py

**Status:** PASS

**Description:** Manual state update with `get_session_state()` and `update_session_state()` between runs.

**Result:** Completed successfully. Manual chocolate addition reflected in final state: `['milk', 'eggs', 'bread', 'chocolate']`.

---

### session_state_multiple_users.py

**Status:** PASS

**Description:** Multi-user state isolation with user-specific shopping lists keyed by user_id/session_id. Uses external global dict.

**Result:** Completed successfully. Two users maintained separate shopping lists. State isolation verified.

---

### dynamic_session_state.py

**Status:** PASS

**Description:** Tool hooks pattern (`customer_management_hook`) to intercept tool calls and modify session_state dynamically. Uses `InMemoryDb()`.

**Result:** Completed successfully. Customer management hook injected state on tool calls. Test analysis confirmed customer isolation worked correctly.

---

### agentic_session_state.py

**Status:** PASS

**Description:** Agent self-manages state with `enable_agentic_state=True` and `add_session_state_to_context=True`. Uses `o3-mini`.

**Result:** Completed successfully. Agent autonomously managed shopping list state: `['milk', 'bread']`.

---
