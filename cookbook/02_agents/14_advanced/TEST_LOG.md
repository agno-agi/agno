# Test Log -- 14_advanced

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### 01_create_cultural_knowledge.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 01 create cultural knowledge. Ran successfully and produced expected output.
**Result:** Completed successfully in 6s.

---

### 02_use_cultural_knowledge_in_agent.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 02 use cultural knowledge in agent. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### 03_automatic_cultural_management.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 03 automatic cultural management. Ran successfully and produced expected output.
**Result:** Completed successfully in 26s.

---

### 04_manually_add_culture.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 04 manually add culture. Ran successfully and produced expected output.
**Result:** Completed successfully in 8s.

---

### advanced_compression.py

**Status:** TIMEOUT
**Tier:** untagged
**Description:** Demonstrates advanced compression. Timed out after 120s - likely making many API calls or stuck.
**Result:** Timed out after 120s.

---

### agent_run_cancel_persistence.py

**Status:** PASS
**Tier:** untagged
**Description:** Cancels an agent run mid-stream and verifies partial content and messages are preserved in the database.
**Result:** Completed successfully. Status=CANCELLED, content preserved, 2 messages persisted.

---

### agent_serialization.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates agent serialization. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---

### background_execution.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates background execution. Ran successfully and produced expected output.
**Result:** Completed successfully in 8s.

---

### background_execution_structured.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates background execution structured. Ran successfully and produced expected output.
**Result:** Completed successfully in 19s.

---

### basic_agent_events.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates basic agent events. Ran successfully and produced expected output.
**Result:** Completed successfully in 3s.

---

### cache_model_response.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates cache model response. Ran successfully and produced expected output.
**Result:** Completed successfully in 2s.

---

### cancel_run.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates cancel run. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### compression_events.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates compression events. Ran successfully and produced expected output.
**Result:** Completed successfully in 26s.

---

### concurrent_execution.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates concurrent execution. Ran successfully and produced expected output.
**Result:** Completed successfully in 49s.

---

### custom_cancellation_manager.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates custom cancellation manager. Ran successfully and produced expected output.
**Result:** Completed successfully in 8s.

---

### custom_logging.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates custom logging. Ran successfully and produced expected output.
**Result:** Completed successfully in 9s.

---

### debug.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates debug. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---

### metrics.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates metrics. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---

### reasoning_agent_events.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates reasoning agent events. Ran successfully and produced expected output.
**Result:** Completed successfully in 83s.

---

### retries.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates retries. Ran successfully and produced expected output.
**Result:** Completed successfully in 8s.

---

### tool_call_compression.py

**Status:** TIMEOUT
**Tier:** untagged
**Description:** Demonstrates tool call compression. Timed out after 120s - likely making many API calls or stuck.
**Result:** Timed out after 120s.

---

### background_execution_concurrency.py

**Status:** PASS (behavior verified live; Postgres variant pending)
**Tier:** untagged
**Description:** Demonstrates the process-wide concurrency limit for background runs (set_background_max_concurrency): 5 runs submitted, at most 2 execute at once, the rest wait as PENDING. Behavior verified live with real OpenAI calls through the actual _arun_background path using InMemoryDb (one session per run): max RUNNING observed at any sample was exactly 2, all 5 runs completed, no errors. The cookbook file itself (PostgresDb variant) was compile-checked only because the pgvector Docker container was unresponsive during testing. The limiter is also covered by unit tests in libs/agno/tests/unit/run/test_background_concurrency.py and libs/agno/tests/unit/agent/test_background_execution.py.
**Result:** Live concurrency behavior PASS (cap held at 2, 5/5 completed); rerun the file against Postgres once the container is healthy.
**Observation:** Testing surfaced a pre-existing issue unrelated to the limiter: multiple concurrent background runs sharing ONE session clobber each other's status updates (each background task saves its own session snapshot; last writer wins), leaving other runs' statuses stale (e.g. PENDING forever) when polled. Runs on distinct sessions are unaffected.

---
