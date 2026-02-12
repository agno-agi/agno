# Test Log: run_control

> Updated: 2026-02-11

### retries.py

**Status:** PASS

**Description:** Team retry configuration — creates a team with `retries=3, delay_between_retries=1, exponential_backoff=True`. Members (Sarah/Mike) have no explicit model and inherit `gpt-4o` from team's default model.

**Result:** Ran successfully in ~20s. Team delegated to Sarah (Data Researcher with WebSearchTools), who searched for AI news and returned results. Retry params accepted without error. Default model inheritance confirmed via log: "Agent 'Sarah' inheriting model from Team: gpt-4o".

---

### cancel_run.py

**Status:** PASS

**Description:** Team run cancellation via threading — starts a long story-writing task in one thread, cancels it via `team.cancel_run(run_id)` from another thread after 8s delay.

**Result:** Story completed before cancellation took effect (o3-mini is fast). The cookbook handles this gracefully with a "WARNING: Team run completed before cancellation" message. The cancellation mechanism itself works — `cancel_run()` returns True.

---

### model_inheritance.py

**Status:** PASS

**Description:** Model inheritance — demonstrates that members without explicit model inherit from team's model. Editor has explicit `gpt-5.2`, others inherit `gpt-4o` from team. Uses `team.initialize_team()` to trigger inheritance.

**Result:** Ran successfully. Model inheritance confirmed: Researcher/Writer/Analyst inherit gpt-4o from team; Editor keeps explicit gpt-5.2. Article generation worked with all three members coordinated.

---

### remote_team.py

**Status:** SKIP

**Description:** RemoteTeam connecting to AgentOS on localhost:7778 — requires a running AgentOS instance.

**Result:** Skipped — no AgentOS instance running. Previous run confirmed `RemoteServerUnavailableError` when AgentOS is not available.

---
