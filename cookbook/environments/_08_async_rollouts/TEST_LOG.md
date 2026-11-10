# Test Log - _08_async_rollouts

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Concurrent typed rollouts through `arun_rollouts()`.

**Result:** `async-edge-a` and `async-edge-b` each passed 3/4 (0.75). All
eight attempts were scored, and both rows were in the true binary learning
zone.

---

### async_export.py

**Status:** PASS

**Description:** Async verification followed by passing-only SFT JSONL export.

**Result:** In the final async-export run, `export-edge-a` passed 1/4 (0.25)
and `export-edge-b` 4/4 (1.00). The learning-zone selection retained the first
task, and `ato_sft_jsonl()` wrote its one passing conversation.

A pre-final live run before switching the export call to its async twin
observed 4/4 and 3/4 and wrote three rows. The final rates above correspond to
the checked-in async code path.

---
