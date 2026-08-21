# Test Log -- 14_advanced

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

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

### redis_event_stream_resume.py

**Status:** PASS (live, real Redis)
**Tier:** untagged
**Description:** Demonstrates cross-process streaming resume with RedisEventStream: a producer starts a background streaming run writing events to Redis Streams; a separate observer (own RedisEventStream instance and client, sharing only Redis) replays missed events and tails live ones to completion. Verified with real OpenAI calls and fakeredis substituted for the Redis client (shared FakeServer = two clients of one Redis) - the exact cookbook code path minus the server: observer replayed missed events, tailed to terminal state, saw COMPLETED and the full output. Rerun against real Redis (./cookbook/scripts/run_redis.sh) when available.
**Result:** PASS against real Redis (redis-stack via run_redis.sh): observer replayed missed events and tailed 51 events to completion, saw COMPLETED and full output.

---

### background_streaming_resume.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates background streaming (background=True, stream=True) with disconnect and resume via the pluggable event stream (get_event_stream). Run live with real OpenAI calls: consumed 3 SSE events, disconnected, run continued in background; replay() returned the 8 missed events and tail() streamed to the terminal state (index 10), with final status COMPLETED and the full poem retrievable via aget_run_output. Also documents RedisEventStream configuration for multi-container resume.
**Result:** Live run PASS end to end (replay, live tail, terminal detection, final output).

---

### background_execution_concurrency.py

**Status:** PASS (live, real Postgres)
**Tier:** untagged
**Description:** Demonstrates the process-wide concurrency limit for background runs: 5 runs submitted (one session each), at most 2 execute at once, the rest wait as PENDING. Run live against pgvector Postgres with real OpenAI calls: all 5 completed in 14s, cap held. Also covered by unit tests in libs/agno/tests/unit/run/test_background_concurrency.py and libs/agno/tests/unit/agent/test_background_execution.py.
**Result:** PASS end to end.
**Observation:** Running the earlier version of this cookbook (all runs sharing the agent's default session) reproduced the known shared-session status-clobbering bug on cue - runs stuck at PENDING forever with free slots (different victims each run: 1 then 2). The transition-site fix ships in the durable run queue PR chain; the cookbook now uses one session per run, which is also the realistic shape.

---

### compression_events.py

**Status:** FAIL
**Date:** 2026-08-20
**Timeout:** 60s

**What was tested:**
- Started the compression events cookbook with `.venvs/demo/bin/python`.
- Verified event stream startup through `RunStarted` and `ModelRequestStarted`.

**Observations:**
- Exited in about 4s without timing out.

**Issues found:**
- OpenAI API returned an organization spend-limit error before tool calls or compression events could complete.

---

### context_compaction.py

**Status:** FAIL
**Date:** 2026-08-20

**What was tested:**
- Reviewed context compaction manager wiring.

**Observations:**
- The cookbook passes `ContextCompactionManager` directly to `Agent(compaction_manager=...)`.

**Issues found:**
- `Agent.compaction_manager` is typed for `CompactionManager`; direct `ContextCompactionManager` construction leaves `agent.compact_context` false and does not use the unified manager path correctly.

---
