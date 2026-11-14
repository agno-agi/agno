# Test Log -- 13_reasoning

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### basic_reasoning.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates basic reasoning. Ran successfully and produced expected output.
**Result:** Completed successfully in 5s.

---

### reasoning_with_model.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates reasoning with model. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### basic_reasoning.py

**Status:** PASS

**Description:** Moved the reasoning model off `o3-mini`, which OpenAI shut down on 2026-10-23 (404), to its listed replacement `gpt-5.6-sol`.

**Result:** Reasoning steps print before the answer. Real OpenAI calls, no mocks.

---

### reasoning_with_model.py

**Status:** PASS

**Description:** Moved the reasoning model off `o3-mini`, which OpenAI shut down on 2026-10-23 (404), to its listed replacement `gpt-5.6-sol`.

**Result:** Reasoning steps print before the answer. Real OpenAI calls, no mocks.

---
