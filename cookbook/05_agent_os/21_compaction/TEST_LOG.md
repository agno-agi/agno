# Test Log -- 21_compaction

> Note: entries below predate the removal of `compact_at_runs` / `compact_at_messages`.
> Compaction now triggers on `compact_at_tokens` only, or on an explicit `agent.compact()`.
> The configurations quoted here no longer construct; the observations still stand.


**Tested:** 2026-09-03
**Environment:** .venvs/demo/bin/python

---

### compaction_os.py

**Status:** PASS

**Description:** Builds an AgentOS serving one agent with
`Compaction(compact_at_runs=4, keep_last_runs=2)` and a cheaper summarization
model. Verified the FastAPI app constructs and the agent resolves its Compaction
config with the expected thresholds.

**Result:** App built successfully; compaction resolved with runs=4, keep=2.

---
