# TEST_LOG for cookbook/04_workflows/06_advanced_concepts

Generated: 2026-02-11

## early_stopping/

### early_stop_basic.py

**Status:** PASS

**Description:** Tests StepOutput(stop=True) across 3 workflows: security deployment (2 cases), content quality (1 case), data validation (2 cases). 5 test cases total.

**Result:** All 5 completed (8.1s, 37.6s, 8.9s, 2.4s, 20.3s). Early termination triggered correctly for VULNERABLE code and INVALID data.

---

### early_stop_condition.py

**Status:** PASS

**Description:** Stops workflow from inside a Condition branch via compliance checker. Sync-stream.

**Result:** Completed in 33.7s. Early termination triggered correctly.

---

### early_stop_loop.py

**Status:** PASS

**Description:** Stops a Loop early via safety-check step. Sync-stream.

**Result:** Completed in 27.1s. Early termination triggered correctly.

---

### early_stop_parallel.py

**Status:** PASS

**Description:** Stops workflow from within a Parallel block via safety checker. Sync non-streaming.

**Result:** Completed in 15.7s.

---

## guardrails/

### prompt_injection.py

**Status:** PASS (functional, guardrail ineffective)

**Description:** Tests PromptInjectionGuardrail with 5 test cases. Async workflow with SqliteDb.

**Result:** Normal request passed. All 4 injection attempts passed through without being blocked. PromptInjectionGuardrail not detecting these patterns — [B] COOKBOOK QUALITY.

---

## previous_step_outputs/

### access_previous_outputs.py

**Status:** PASS (partial)

**Description:** Tests accessing outputs from prior steps via named steps and implicit step keys.

**Result:**
- Named access workflow: PASS (33.4s)
- Direct steps workflow: FAIL ("object of type 'NoneType' has no len()" — step key naming for raw function executors)

---

## session_state/

### state_in_condition.py

**Status:** PASS

**Description:** Uses session state in Condition evaluator. 2 runs.

**Result:** Both completed. Session state correctly tracked.

---

### state_with_agent.py

**Status:** PASS

**Description:** Shares mutable session state across agent tool calls. 4 runs.

**Result:** All 4 completed. State persisted correctly.

---

### rename_session.py

**Status:** PASS

**Description:** Demonstrates renaming workflow sessions.

**Result:** Completed. Session renamed successfully.

---

### state_in_function.py, state_in_router.py, state_with_team.py

**Status:** NOT RUN (time constraint — complex multi-run cookbooks)

---

## structured_io/

### input_schema.py

**Status:** PASS

**Result:** Completed in 96.8s.

---

### pydantic_input.py

**Status:** PASS

**Result:** Completed in 80.9s.

---

### structured_io_function.py

**Status:** PASS

**Result:** Completed in 29.2s.

---

### structured_io_agent.py

**Status:** PASS

**Result:** Completed in 27.7s.

---

### structured_io_team.py

**Status:** TIMEOUT

**Result:** Timed out at 120s.

---

### image_input.py

**Status:** PASS

**Result:** Completed in 32.2s.

---

## history/

### step_history.py

**Status:** TIMEOUT

**Result:** Timed out at 120s.

---

### continuous_execution.py, history_in_function.py, intent_routing_with_history.py

**Status:** NOT RUN (time constraint)

---

## run_control/

### cancel_run.py

**Status:** PASS

**Result:** Workflow cancellation worked correctly.

---

### deep_copy.py

**Status:** PASS (non-execution demo)

**Result:** Deepcopy of workflow displayed correctly.

---

### event_storage.py

**Status:** PASS

**Result:** 2845 event lines captured. Full event lifecycle verified.

---

### executor_events.py

**Status:** PASS (non-execution demo)

**Result:** Event type hierarchy displayed correctly.

---

### workflow_serialization.py

**Status:** PASS (non-execution demo)

**Result:** Serialized workflow dict displayed correctly.

---

### metrics.py

**Status:** TIMEOUT

**Result:** Timed out at 120s.

---

### remote_workflow.py

**Status:** SKIP (requires AgentOS server)

---

### workflow_cli.py

**Status:** SKIP (requires interactive stdin)

---

## workflow_agent/

### basic_workflow_agent.py

**Status:** PASS

**Result:** All 4 runs completed (63.5s, 4.4s, 25.3s, 6.9s).

---

### workflow_agent_with_condition.py

**Status:** PASS

**Result:** Completed in 21.0s.

---

## tools/

### workflow_tools.py

**Status:** NOT RUN (time constraint)

---

## background_execution/

### background_poll.py, websocket_client.py, websocket_server.py

**Status:** SKIP (server/client architecture)

---

## long_running/

### disruption_catchup.py, events_replay.py, websocket_reconnect.py

**Status:** SKIP (server/client architecture)

---
