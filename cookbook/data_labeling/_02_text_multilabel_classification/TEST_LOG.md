# Test Log - _02_text_multilabel_classification

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Tags three restaurant reviews with any subset of {food, service, value, atmosphere, cleanliness} using an output_schema with a List[Literal] field.

**Result:** All three runs returned valid Tagging objects. "Pasta was excellent and our server was attentive. A bit pricey but worth it." -> tags=['food', 'service', 'value']; "Place was filthy. Floors sticky, bathroom unusable." -> tags=['cleanliness']; "Came for the vibes, stayed for the cocktails. The space is gorgeous." -> tags=['food', 'atmosphere'] (cocktails counted under food).

---

### hierarchical.py

**Status:** PASS

**Description:** Tags two news snippets with parent/child pairs from a two-level taxonomy (parent constrained to a Literal of 5 topics, child free-text subtopic).

**Result:** Fed/markets snippet -> [business/markets, tech/ai, tech/hardware]; Manchester United snippet -> [sports/football]. All parents valid Literal values, children are sensible subtopics.

---

### with_confidence.py

**Status:** PASS

**Description:** Same aspect-tagging task with a per-tag confidence field (high/medium/low Literal) on three reviews including one deliberately vague input.

**Result:** "Pasta was excellent and the server brought refills without asking." -> food/high, service/high; "Not sure I'd come back. Something was off." -> atmosphere/low, food/low, service/low (this run tagged the vague review with three low-confidence guesses rather than an empty list); "Cocktails were $22. The room is loud. Food was fine." -> food/high, atmosphere/high, value/high.

---
