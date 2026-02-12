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


---

## v2.5 Audit Results

# Approvals Cookbook Test Log

## Test Run: 2026-02-11 UTC (v2.5 three-layer review)

### approval_basic.py

**Status:** PASS

**Description:** Basic @approval + @tool(requires_confirmation=True) with SQLite. Verifies agent pauses, approval record created in DB, requirement confirmed, run continues, approval resolved.

**Result:** All 5 steps passed. Approval record created with correct tool name, status lifecycle (pending -> approved) verified, agent produced expected output after continuation.

---

### approval_async.py

**Status:** PASS

**Description:** Async variant using arun() and acontinue_run(). Same verification steps as approval_basic.py.

**Result:** All 5 steps passed. Async approval creation and resolution worked correctly.

---

### approval_user_input.py

**Status:** PASS

**Description:** @approval + @tool(requires_user_input=True). Creates persistent approval record AND requires user input before tool execution.

**Result:** All 5 steps passed. Approval record created, user input provided via continue_run, approval resolved, agent completed with correct output.

---

### approval_external_execution.py

**Status:** PASS

**Description:** @approval + @tool(external_execution=True). Creates persistent approval record for externally-executed tools.

**Result:** All 5 steps passed. Approval record created, external result set, approval resolved, agent completed.

---

### approval_list_and_resolve.py

**Status:** PASS

**Description:** Full approval lifecycle: pause, list, filter, resolve, delete. Simulates external API client flow with two concurrent approvals.

**Result:** All checks passed. Two pending approvals created and listed correctly. Filtering by run_id returned exactly 1 result. First approved, double-resolve guard (expected_status) worked. Second rejected. Both continuations handled correctly. All records deleted.

---

### approval_team.py

**Status:** PASS

**Description:** Team-level approval: member agent tool with @approval. Verifies team pauses, approval record has source_type=team.

**Result:** All 5 steps passed. Team correctly paused, approval record created with source_type=team. Team completed after confirmation.

---

### audit_approval_confirmation.py

**Status:** PASS

**Description:** @approval(type="audit") + @tool(requires_confirmation=True). Audit record created AFTER HITL resolves. Tests both approval and rejection paths.

**Result:** All checks passed. Approval path: audit record created with status=approved. Rejection path: audit record created with status=rejected. Total 2 audit records logged.

---

### audit_approval_async.py

**Status:** PASS

**Description:** Async variant of audit_approval_confirmation using arun() and acontinue_run().

**Result:** All checks passed. No approval records before HITL resolution (correct for audit type). Audit record created with status=approved after confirmation.

---

### audit_approval_external.py

**Status:** PASS

**Description:** @approval(type="audit") + @tool(external_execution=True). Audit record created after external tool execution.

**Result:** All checks passed. No approval records before HITL resolution. Audit record created with status=approved, approval_type=audit after external result provided.

---

### audit_approval_overview.py

**Status:** PASS

**Description:** Side-by-side comparison: @approval (type="required") vs @approval(type="audit") in the same agent. Demonstrates blocking vs logging approval types.

**Result:** All 7 steps passed. Required approval: pending record created before execution, resolved after. Audit approval: no record until after HITL resolves. Filtering by approval_type correctly separated the two records.

---

### audit_approval_user_input.py

**Status:** PASS

**Description:** @approval(type="audit") + @tool(requires_user_input=True). Audit record created after user provides input and tool executes.

**Result:** All checks passed. No logged approvals before user input. Audit record created with status=approved after user input provided. Agent completed with correct output.

---
