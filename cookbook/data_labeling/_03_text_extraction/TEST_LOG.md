# Test Log - _03_text_extraction

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### basic.py

**Status:** PASS

**Description:** Extract `Contact` (name, email, phone, company, title) from email-signature-style text.

**Result:** All fields extracted verbatim; missing fields left null.

---

### nested.py

**Status:** PASS

**Description:** Extract a `Meeting` containing a list of nested `ActionItem`s from a meeting transcript.

**Result:** Three action items extracted with correct owners and due dates.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with `ConfidentField` wrapping each value.

**Result:** Confidences are sensible: high for explicit fields, medium for inferred ones (e.g. "@mike" as a name).

---
