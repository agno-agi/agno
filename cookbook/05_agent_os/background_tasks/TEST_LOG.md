# Test Log: background_tasks

> Tests not yet run. Run each file and update this log.

### background_evals_example.py

**Status:** PENDING

**Description:** Example: Per-Hook Background Control with AgentAsJudgeEval in AgentOS.

---

### background_hooks_decorator.py

**Status:** PENDING

**Description:** Example: Using Background Post-Hooks in AgentOS.

---

### background_hooks_example.py

**Status:** PENDING

**Description:** Example: Using Background Post-Hooks in AgentOS.

---

### background_hooks_team.py

**Status:** PENDING

**Description:** Example: Background Hooks with Teams in AgentOS.

---

### background_hooks_workflow.py

**Status:** PENDING

**Description:** Example: Background Hooks with Workflows in AgentOS.

---

### background_output_evaluation.py

**Status:** PENDING

**Description:** Example: Background Output Evaluation with Agent-as-Judge.

---

### evals_demo.py

**Status:** PENDING

**Description:** Simple example creating a session and using the AgentOS with a SessionApp to expose it.

---

### redis_event_stream.py

**Status:** NOT RUN (compile-checked)
**Tier:** untagged
**Description:** AgentOS configured via queue=QueueConfig(max_concurrency=16, redis=URL), which wires RedisEventStream + RedisRunCancellationManager from shared clients, plus RedisDb storage on the same Redis, enabling cross-replica background streaming resume (start a run on one replica, hit /resume on another). Serve-style example; requires a running Redis and multiple replicas to demonstrate. The underlying event stream behavior is covered by unit tests (libs/agno/tests/unit/os/test_event_streams_redis.py) and the library-level cookbook cookbook/02_agents/14_advanced/redis_event_stream_resume.py.
**Result:** Compile check passed; full run requires Redis and a multi-replica setup.

---

### durable_queue.py

**Status:** PASS (live end-to-end, real Postgres)
**Tier:** untagged
**Description:** AgentOS with QueueConfig(durable=True) smoke-tested over HTTP against pgvector Postgres with real OpenAI calls: submit (202 with PENDING, row committed), duplicate submit with the same Idempotency-Key returned the SAME run_id, poll reached COMPLETED with content, /queue/stats and /queue/jobs/{id} returned correct counts and job state (attempt 1, key recorded). Incidental durability proof: two jobs accepted by an earlier server process (which then died) were recovered and executed by the next server's worker - accepted-then-crashed runs completed after restart.
**Result:** PASS end to end. Also caught and fixed a real bug during testing: the sync PostgresDb queue methods were awaited directly (resolve_queue_store now wraps sync stores in an awaitable thread adapter).

---

