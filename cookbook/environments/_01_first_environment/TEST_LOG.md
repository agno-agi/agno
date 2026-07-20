# Test Log - _01_first_environment

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** First typed-output environment with an easy anchor and two calibrated chained products at K=4.

**Result:** Live run completed with 12/12 scored attempts and no unscored attempts. Observed rates: `easy-product` 4/4 (1.00), `chained-product-a` 2/4 (0.50), `chained-product-b` 2/4 (0.50). Both chained rows landed in the true partial pass-rate learning zone.

---

### with_summary.py

**Status:** PASS

**Description:** Reads overall and per-task statistics from `summary()`.

**Result:** Live run completed with 12/12 scored attempts and no unscored attempts. Observed rates: `easy-product` 4/4 (1.00), `chained-product-a` 3/4 (0.75), `chained-product-c` 4/4 (1.00). `summary()` reported an overall pass rate of 11/12 and correctly marked only `chained-product-a` as the learning-zone row.

---

### with_fingerprints.py

**Status:** PASS

**Description:** Shows the environment and policy fingerprints retained on the result.

**Result:** Final live run completed with 12/12 scored attempts and no unscored attempts. Observed rates: `easy-product` 4/4 (1.00), `chained-product-a` 2/4 (0.50), `chained-product-b` 3/4 (0.75). The result matched the environment fingerprint. The first calibration used two different chained products and saturated at 4/4 on all three rows; those tasks were replaced before this passing run.

---
