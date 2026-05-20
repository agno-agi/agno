# Test Log - _10_audio_classification

Tested 2026-05-17 against `gemini-3-flash-preview` (Gemini), agno 2.6.6. Input is `agno-public/demo_data/QA-01.mp3` (English Q&A clip).

### basic.py

**Status:** PASS

**Description:** Classify audio clip language from a closed set.

**Result:** Identified as `english`.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with a `confidence` field.

**Result:** `english`, confidence `high`.

---
