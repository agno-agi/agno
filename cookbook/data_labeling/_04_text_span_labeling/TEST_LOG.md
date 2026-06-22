# Test Log - _04_text_span_labeling

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

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
