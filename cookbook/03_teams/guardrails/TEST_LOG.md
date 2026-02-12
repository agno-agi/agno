# Test Log: guardrails

> Updated: 2026-02-11

### openai_moderation.py

**Status:** PASS

**Description:** Demonstrates `OpenAIModerationGuardrail` as a pre-hook on a team with 4 test cases: safe input, borderline, hate speech, and custom moderation categories (violence only).

**Result:** All 4 test cases completed. Safe input passed through, borderline processed normally, hate speech and custom-category violations correctly detected and blocked. Duration ~17s.

---

### pii_detection.py

**Status:** PASS

**Description:** Demonstrates `PIIDetectionGuardrail` in both blocking and masking modes with 8 test cases covering email addresses, credit card numbers, phone numbers, and SSNs.

**Result:** All 8 tests completed. Blocking mode correctly raised errors for PII-containing inputs. Masking mode replaced sensitive data with asterisks while allowing the request through. Duration ~15s.

---

### prompt_injection.py

**Status:** PASS

**Description:** Demonstrates `PromptInjectionGuardrail` as a pre-hook with 5 test cases: normal, system prompt override, role-play exploit, jailbreak attempt, and subtle injection.

**Result:** All 5 tests completed. Normal input passed through. All 4 injection attempts were correctly detected and blocked. Duration ~2s.

---
