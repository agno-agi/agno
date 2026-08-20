# Test Log -- 08_guardrails



## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| prompt_injection.py | PASS | guardrail trips logged as designed |

---

## Verification - 2026-08-18 round 3 (feat/v3.0, base b10e70d5d4)

**Environment:** `.venvs/demo/bin/python`, batch runner with 240s timeout

| File | Status | Note |
|---|---|---|
| custom_guardrail.py | PASS |  |
| pii_detection.py | PASS | guardrail trips logged as expected |

---

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
