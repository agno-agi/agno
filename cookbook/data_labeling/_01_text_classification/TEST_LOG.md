# Test Log - _01_text_classification

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Sentiment classification (positive/negative/neutral) over three product reviews using an output_schema with a single Literal label field.

**Result:** All three samples classified as expected: "I love this product, fantastic quality and fast shipping." -> positive; "Broken on arrival, total waste of money." -> negative; "It works as described, nothing special." -> neutral.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task as basic.py with an extra `confidence` field (high/medium/low) on the output, to support routing low-confidence labels to a human queue.

**Result:** Confidence tracked ambiguity as intended: "Best purchase of my life, life-changing!" -> positive/high; "It's fine I guess." -> neutral/medium; "Yeah right, this thing is 'amazing'." (sarcasm) -> negative/low.

---

### with_rationale.py

**Status:** PASS

**Description:** Same task with a free-text `rationale` field alongside each label; instructions ask the model to quote or paraphrase the deciding words.

**Result:** Both labels correct with rationales citing the deciding phrases: "Shipping was fast but the product itself fell apart in a week." -> negative ("...the product quickly fell apart within a week"); "Better than expected, will buy again." -> positive (quotes 'Better than expected' and 'will buy again').

---
