# Test Log - _01_first_environment

## Re-test 2026-07-20 — fix/cookbooks-claude (Agno 2.8.0 source)

2.8.0 defines the learning zone as `0 < pass_rate < 1` (mixed pass/fail), so a k=4
file whose one hard task can land 4/4 saturates on unlucky runs.

### with_summary.py — FIXED

**Fix:** `chained-product-c` (which shared the edge with `chained-product-a` and
saturated together this run) replaced with a second, independent calibrated chain
(`chained-product-b`, expected 10481347), so a zone row is reliable at k=4.

**Grid (k=4):** `easy-product` 4/4; `chained-product-a` 3/4 (0.75, zone);
`chained-product-b` 4/4.

`basic.py` (chained-product-a 2/4, zone) and `with_fingerprints.py` (a=2/4, b=3/4,
two zones) re-ran clean and unchanged.

---

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
