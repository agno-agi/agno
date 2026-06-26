# Test Log - _01_text_classification

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Sentiment classification (positive/negative/neutral) over three product reviews.

**Result:** All three samples classified as expected.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task as basic.py with an extra `confidence` field on the output.

**Result:** Classifications correct; confidence tracks ambiguity (e.g. "It's fine I guess." -> neutral, medium).

---

### with_rationale.py

**Status:** PASS

**Description:** Same task with a free-text rationale alongside each label.

**Result:** Rationales correctly cite the deciding phrases in each input.

---
