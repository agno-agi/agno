# TEST LOG

Generated: 2026-02-10 UTC

Pattern Check: Checked 5 file(s) in cookbook/02_agents/guardrails. Violations: 0

### custom_guardrail.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### openai_moderation.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### output_guardrail.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### pii_detection.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### prompt_injection.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

### custom_guardrail.py

**Status:** PASS

**Description:** Custom BaseGuardrail subclass with blocked-terms detection. Safe content ("secure password management") processed successfully without triggering the guardrail.

**Result:** Completed successfully.

---

### openai_moderation.py

**Status:** PASS

**Description:** OpenAI moderation guardrail with 4 tests. Test 1: safe content passed. Tests 2-3: violence/hate speech blocked by guardrail (note: pre_hooks handle blocking before the try/except, so "[WARNING]" prints are expected — the guardrail IS blocking correctly). Test 4: image moderation with custom categories (violence + hate) blocked violent image.

**Result:** Completed successfully. All guardrails triggered correctly.

---

### output_guardrail.py

**Status:** PASS

**Description:** Output length post_hook guardrail. Agent response to "clean architecture" prompt produced substantial content (>20 chars), passing the output check.

**Result:** Completed successfully.

---

### pii_detection.py

**Status:** PASS

**Description:** PII detection guardrail with 8 tests. Tests 1: safe request passed. Tests 2-7: SSN, credit card, email, phone, multiple PII types, and edge-case formatting all correctly blocked with InputCheckError. Test 8: mask_pii=True mode replaced SSN with placeholder, allowing request through.

**Result:** Completed successfully. All PII types detected and blocked/masked correctly.

---

### prompt_injection.py

**Status:** PASS

**Description:** Prompt injection guardrail with 5 tests. Test 1: normal joke request passed. Tests 2-5: basic injection ("ignore previous instructions"), DAN-style, jailbreak attempt, and subtle injection all correctly blocked with InputCheckError.

**Result:** Completed successfully. All injection patterns detected and blocked.

---
