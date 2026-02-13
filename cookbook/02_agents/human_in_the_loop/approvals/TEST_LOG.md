# Approvals Cookbook Test Log

## Test Run: 2026-02-10

### approval_basic.py

**Status:** PASS

**Description:** Basic agent approval with SQLite. Runs an agent with `@tool(requires_approval=True)`, verifies the agent pauses, checks that an approval record is created in the DB, confirms the requirement, continues the run, resolves the approval, and verifies clean state.

**Result:** All 5 steps passed. Approval record created with correct tool name (`get_top_hackernews_stories`), status lifecycle (pending -> approved) verified, and agent produced expected output after continuation.

---

### approval_async.py

**Status:** PASS

**Description:** Async variant of the basic approval flow using `arun()` and `acontinue_run()`. Same verification steps as `approval_basic.py`.

**Result:** All 5 steps passed. Async approval creation and resolution worked correctly. Agent completed successfully after async continuation.

---

### approval_team.py

**Status:** PASS

**Description:** Team-level approval where a member agent's tool (`deploy_to_production`) requires approval. Verifies the team pauses, approval record is created in the DB with correct source type (`team`), and the team completes after confirmation.

**Result:** All 5 steps passed. Team correctly paused when member agent encountered an approval-requiring tool. Approval record created with `source_type=team` and `tool_names=['deploy_to_production']`. Team completed deployment after confirmation.

---

### approval_list_and_resolve.py

**Status:** PASS

**Description:** Full approval lifecycle simulating an external API client. Creates two agent runs that pause (delete_user_data and send_bulk_email), lists all pending approvals, filters by run_id, approves one, tests double-resolve guard (expected_status), rejects the other, continues both runs, and deletes all approval records.

**Result:** All checks passed. Two pending approvals created and listed correctly. Filtering by run_id returned exactly 1 result. First approval approved, double-resolve correctly blocked by expected_status guard. Second approval rejected. Agent handled both approved (tool executed) and rejected (graceful refusal) continuations. All approval records deleted successfully.

---
