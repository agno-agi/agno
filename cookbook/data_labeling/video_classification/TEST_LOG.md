# Test Log - video_classification

Tested 2026-05-17 against `gemini-3-flash-preview` (Gemini), agno 2.6.6. Input is `agno-public/demo/sample_seaview.mp4` (note: actual clip is a lab/microscope scene, not a seaview — sample asset name is misleading).

### basic.py

**Status:** PASS

**Description:** Single-label classification of the clip's scene type.

**Result:** Classified as `indoor` (consistent with the actual lab scene).

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with a `confidence` field.

**Result:** Classified as `people` with `high` confidence (model picks a different valid label than basic.py — both are reasonable for a person in a lab).

---
