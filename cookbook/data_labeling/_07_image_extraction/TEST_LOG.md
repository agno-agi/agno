# Test Log - _07_image_extraction

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Extract a `Scene` (subject, setting, time of day, colors, objects) from a photo of Krakow's St. Mary's Basilica.

**Result:** All fields populated correctly.

**Note:** Test image switched from a Wikimedia URL (Gemini can't fetch those) to `agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg`.

---

### ocr_fields.py

**Status:** PASS

**Description:** OCR a text-heavy image into typed fields (primary text, secondary text, color scheme).

**Result:** Reads the Agno wordmark and body copy from the intro image into the typed schema.

**Note:** Input switched from a Wikimedia "Welcome to Las Vegas" sign (Gemini can't fetch those URLs) to `agno-public.s3.us-east-1.amazonaws.com/images/agno-intro.png`. The schema is still about extracting text from an image — content changed from a sign to a marketing graphic.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with `ConfidentStr` / `ConfidentList` wrapping each output (fjord landscape from the gstatic gallery).

**Result:** All fields populated with `high` confidence; nested confidence wrappers serialize correctly.

---
