# Test Log -- 08_guardrails

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### custom_guardrail.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates custom guardrail. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### openai_moderation.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates openai moderation. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### output_guardrail.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates output guardrail. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---

### pii_detection.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates pii detection. Ran successfully and produced expected output.
**Result:** Completed successfully in 20s.

---

### prompt_injection.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates prompt injection. Ran successfully and produced expected output.
**Result:** Completed successfully in 4s.

---

## Jev integration — 2026-09-21

Validation used `.venv/Scripts/python.exe` with mocked providers. No live API quality or latency claims are established.

### jev_guardrail.py

**Status:** PASS (mocked)

**Description:** Mocked input/output hooks with built-in checks, custom off-topic policy, thresholds, and pretty-printed rejection diagnostics.

**Result:** Cookbook smoke test passed.

### jev_grounding.py

**Status:** PASS (mocked)

**Description:** Mocked input screening and output grounding against explicit evidence; pretty-printed run result.

**Result:** Cookbook smoke test passed.
