# Test Log - _13_video_classification

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

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
