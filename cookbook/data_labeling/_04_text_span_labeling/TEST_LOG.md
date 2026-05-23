# Test Log - _04_text_span_labeling

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### basic.py

**Status:** PASS

**Description:** NER over a short sentence; agent returns exact substrings, Python computes offsets.

**Result:** Five entities found (DATE, PERSON, ORG, LOCATION, ORG) with correct offsets.

---

### pii_redaction.py

**Status:** PASS

**Description:** Detect PII spans (name, phone, email, credit card) and produce a redacted string.

**Result:** All four PII items detected; redacted text replaces each span with its tag.

---
