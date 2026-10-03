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

## IsMalicious offline regression, 2026-10-03

### ismalicious_guard.py

**Status:** PASS (offline)

**Description:** Ran `libs/agno/tests/unit/cookbook/test_ismalicious_guard.py`
with Agno from this checkout, Python 3.12.8 and synthetic HTTP transports.
External TCP sockets were disabled; only internal Unix sockets were permitted.

**Result:** 64 tests passed, including ten native `Agent.run` call-chain cases
across `OpenAIChat` and `OpenAIResponses`. URL/content block and warn decisions
prevent the next model request; allow preserves the exact text. No live API,
model credentials or detector-accuracy claim.

### ismalicious_untrusted_content.py

**Status:** NOT RUN (live demonstration)

**Description:** The demo now uses `OpenAIResponses` with `gpt-5.6-luna` per
the cookbook conventions. Its provider's native tool boundary is covered by
the offline regression above. The standalone demonstration requires the
operator's model and IsMalicious credentials and was not invoked.

---
