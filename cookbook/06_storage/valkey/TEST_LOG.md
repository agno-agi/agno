# Test Log: valkey

### valkey_for_agent.py

**Status:** PASS

**Description:** Runs an agent backed by ValkeyDb, asks two follow-up questions with history in context, and verifies sessions are persisted via `get_sessions`.

**Result:** Agent answered both turns (correctly resolved "their" from prior turn via history); `get_sessions` reported 3 agent sessions persisted in Valkey. Re-tested after learnings/isolation additions: both turns answered, 2 sessions persisted on a fresh server.

---

### valkey_for_team.py

**Status:** PASS

**Description:** Runs a HackerNews + web-search team backed by ValkeyDb with `output_schema=Article`, and persists team/member sessions.

**Result:** Team completed and returned a valid structured `Article` (title, summary, reference_links); team session index present in Valkey. Note: the external DuckDuckGo (`ddgs`) web search intermittently failed with RemoteProtocolError/TimeoutException and was retried; total run took ~13 min. This is an upstream web-search flakiness, not a Valkey/cookbook issue. Re-tested after learnings/isolation additions: completed with a valid structured Article.

---

### valkey_for_workflow.py

**Status:** PASS

**Description:** Runs a two-step workflow (research team then content planner) using `ValkeyDb(session_table="workflow_session")`.

**Result:** Workflow completed in ~444s and produced a 4-week content plan; workflow session index (`workflow_id:content-creation-workflow`) present in Valkey. Re-tested after learnings/isolation additions: completed in ~223s with a 4-week content plan.

---
