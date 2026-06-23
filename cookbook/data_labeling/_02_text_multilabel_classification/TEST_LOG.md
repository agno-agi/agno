# Test Log - _02_text_multilabel_classification

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Tag restaurant reviews with any subset of {food, service, value, atmosphere, cleanliness}.

**Result:** Tags match the aspects mentioned in each review.

---

### hierarchical.py

**Status:** PASS

**Description:** Two-level (parent/child) tagging on news snippets.

**Result:** Tags correctly nested (e.g. business -> markets, tech -> ai chips).

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with per-tag confidence.

**Result:** Reasonable tag/confidence pairs; empty list returned when no aspects are addressed.

---
