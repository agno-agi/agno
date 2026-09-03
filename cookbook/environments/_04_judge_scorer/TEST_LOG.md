# Test Log - _04_judge_scorer

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Binary rubric judging over two constrained support rewrites at K=4.

**Result:** Final live run scored all 8 attempts with no unscored attempts. Observed rates: `refund-delay` 3/4 (0.75) and `lost-edits` 3/4 (0.75). The first calibration was 0/4 on both rows because the rubric required a concrete follow-up window while the policy prompt discouraged inventing one; the prompt was corrected to allow a process-update commitment before rerunning.

---

### numeric_rubric.py

**Status:** PASS

**Description:** Numeric rubric at raw threshold 9 with separate score-variation and partial-pass reporting at K=4.

**Result:** Live run scored all 8 attempts with no unscored attempts. Observed rates: `refund-delay` 1/4 (0.25), normalized values `[0.7778, 0.8889, 0.6667, 0.7778]`; `lost-edits` 3/4 (0.75), normalized values `[0.7778, 1.0, 0.8889, 1.0]`. Both rows appeared in the API score-variation zone and in the separately computed true partial pass-rate set.

---

### with_reference.py

**Status:** PASS

**Description:** Binary semantic comparison against a fenced reference answer at K=4.

**Result:** Live run scored all 8 attempts with no unscored attempts. Observed rates: `reference-chain-a` 2/4 (0.50) and `reference-chain-b` 2/4 (0.50). Both binary judge rows landed in the true partial pass-rate learning zone.

---
