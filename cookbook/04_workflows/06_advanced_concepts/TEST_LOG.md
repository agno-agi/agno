# TEST_LOG for cookbook/04_workflows/06_advanced_concepts

Generated: 2026-02-08 16:39:09

### background_execution/background_poll.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG *** Agent Run End: 279bd889-9bd2-42b5-9b88-1d665ea235cd ****

---

### background_execution/websocket_client.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 8s).

**Result:** Startup validation completed. [ERROR] Failed to connect: Multiple exceptions: [Errno 61] Connect call failed

---

### background_execution/websocket_server.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 8s).

**Result:** Startup validation only; process terminated after 8.14s. INFO: Finished server process [29101]

---

### early_stopping/early_stop_basic.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. ┃ • Endpoint breakdown: top routes by latency and errors ┃

---

### early_stopping/early_stop_condition.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. ddgs.exceptions.DDGSException: No results found.

---

### early_stopping/early_stop_loop.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 14.3s

---

### early_stopping/early_stop_parallel.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. ┃ responsible for AI-driven errors or harms. ┃

---

### guardrails/prompt_injection.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. ERROR Validation failed: Potential jailbreaking or prompt injection detected.

---

### history/continuous_execution.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. Student :

---

### history/history_in_function.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. Content Manager :

---

### history/intent_routing_with_history.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. - 'I'm getting an error message'

---

### history/step_history.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. fit their needs.

---

### long_running/disruption_catchup.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 2s).

**Result:** Startup validation only; process terminated after 2.01s. Starting test in 2 seconds...

---

### long_running/events_replay.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 2s).

**Result:** Startup validation only; process terminated after 2.01s. Starting test in 2 seconds...

---

### long_running/websocket_reconnect.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: startup, timeout: 2s).

**Result:** Startup validation only; process terminated after 2.01s. Starting test in 2 seconds...

---

### previous_step_outputs/access_previous_outputs.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Getting top 15 stories from Hacker News

---

### run_control/cancel_run.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Workflow cancellation example completed

---

### run_control/deep_copy.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. First Step: Draft Outline Copy

---

### run_control/event_storage.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Creating new sync OpenAI client for model gpt-5.2

---

### run_control/executor_events.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. DEBUG Marked run 544da40f-5099-4686-a1fe-b9dcd4e537c6 as RunStatus.completed

---

### run_control/metrics.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Creating new sync OpenAI client for model gpt-4o

---

### run_control/remote_workflow.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Error: Failed to connect to remote server at http://localhost:7777

---

### run_control/workflow_cli.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. ┃ • Add observability and safety: logs/metrics, error handling, retries, ┃

---

### run_control/workflow_serialization.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. ERROR Error saving workflow: Label 'serialization-demo' already exists for

---

### session_state/rename_session.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Exited with code 1. AttributeError: 'NoneType' object has no attribute 'session_data'

---

### session_state/state_in_condition.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 3.2s

---

### session_state/state_in_function.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG Creating new sync OpenAI client for model gpt-4o

---

### session_state/state_in_router.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. - Useful large-scale quantum computing likely requires **quantum error

---

### session_state/state_with_agent.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Final workflow session state: {'shopping_list': []}

---

### session_state/state_with_team.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG [ERROR] Step 'Write Tests' not found in the list

---

### structured_io/image_input.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. Completed in 22.9s

---

### structured_io/input_schema.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. DEBUG ********************** TOOL METRICS **********************

---

### structured_io/pydantic_input.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. ddgs.exceptions.DDGSException: No results found.

---

### structured_io/structured_io_agent.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. /Users/ab/conductor/workspaces/agno/colombo/cookbook/04_workflows/06_advanced_concepts/structured_io/structured_io_agent.py:65: PydanticDeprecatedSince20: `min_items` is deprecated and will be removed, use `min_length` i

---

### structured_io/structured_io_function.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Executed successfully. /Users/ab/conductor/workspaces/agno/colombo/cookbook/04_workflows/06_advanced_concepts/structured_io/structured_io_function.py:83: PydanticDeprecatedSince20: `min_items` is deprecated and will be removed, use `min_length

---

### structured_io/structured_io_team.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. /Users/ab/conductor/workspaces/agno/colombo/cookbook/04_workflows/06_advanced_concepts/structured_io/structured_io_team.py:65: PydanticDeprecatedSince20: `min_items` is deprecated and will be removed, use `min_length` in

---

### tools/workflow_tools.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 35s).

**Result:** Timed out after 35s. involvement from IBM, targeting error challenges in quantum computing.

---

### workflow_agent/basic_workflow_agent.py

**Status:** FAIL

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 120s).

**Result:** Timed out after 120s. DEBUG ********************** TOOL METRICS **********************

---

### workflow_agent/workflow_agent_with_condition.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal, timeout: 120s).

**Result:** Executed successfully. Completed in 13.5s

---
