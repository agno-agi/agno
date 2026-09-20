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

### jev_guardrail.py

**Status:** PASS

**Description:** `JevGuardrail` as a pre-hook (prompt_injection, pii and a custom off_topic check) and as a post-hook (medical_advice, toxicity) on an OpenAI travel agent. Run with `.venv/Scripts/python.exe` (Windows, Python 3.12, typesafe-sdk 0.7.0), live TypeSafe and OpenAI APIs, 2026-09-21.

**Result:** The Kyoto question passed. The instruction-override message was blocked with PROMPT_INJECTION (0.99), the passport/card message with PII_DETECTED (0.98), and the linked-list request with OFF_TOPIC (0.99). Each block carried the per-check probabilities in `additional_data`. Blocked runs come back with `RunStatus.error`.

---
