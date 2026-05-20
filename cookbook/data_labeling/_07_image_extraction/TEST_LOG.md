# Test Log - _07_image_extraction

Tested 2026-05-17 against `gpt-5.5` (OpenAIResponses), agno 2.6.6. Inputs are public Wikimedia URLs.

### basic.py

**Status:** PASS

**Description:** Extract a `Scene` (subject, setting, time of day, colors, objects) from a Golden Gate Bridge photo.

**Result:** All fields populated correctly.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with `ConfidentField` / `ConfidentList` wrapping each output (Eiffel Tower image).

**Result:** All fields populated with `high` confidence; nested confidence wrappers serialize correctly.

---

### ocr_fields.py

**Status:** PASS

**Description:** OCR a sign image into typed fields (primary text, secondary text, color scheme).

**Result:** "Welcome to Fabulous Las Vegas / NEVADA" read correctly with multi-color palette.

**Note:** Original URL (`Stop_sign_London_2020.jpg`) was 404. Replaced with the canonical Las Vegas welcome-sign URL (verified via Wikimedia API); also gives a richer multi-text example than a single-word stop sign.

---
