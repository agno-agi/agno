# Test Log - _03_code_scorer

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Named Boolean `CodeScorer` over typed integer output at K=4.

**Result:** Live run scored 8/8 attempts with no unscored attempts. Observed rates: `chained-product-a` 3/4 (0.75) and `chained-product-b` 3/4 (0.75). Both Boolean-score rows were true partial pass-rate learning-zone tasks.

---

### continuous_score.py

**Status:** PASS

**Description:** Continuous component score with a 1.0 pass threshold at K=4.

**Result:** Live run scored 8/8 attempts with no unscored attempts. Observed rates: `audited-chain-a` 4/4 (1.00) with component values `[1.0, 1.0, 1.0, 1.0]`; `audited-chain-b` 3/4 (0.75) with values `[1.0, 0.0, 1.0, 1.0]`. The second row supplied the true partial pass-rate band while the scorer retained graded component-credit behavior.

---

### custom_score.py

**Status:** PASS

**Description:** Custom async scorer returning `Score.reason` and `Score.detail` at K=4.

**Result:** Live run scored 8/8 attempts with no unscored attempts. Observed rates: `chained-product-a` 3/4 (0.75) and `chained-product-c` 3/4 (0.75). Failed `Score.detail` values retained the actual integer, expected integer, and absolute error for drilldown.

---
