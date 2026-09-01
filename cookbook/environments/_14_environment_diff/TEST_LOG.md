# Test Log - _14_environment_diff

## Re-test 2026-07-20 — fix/cookbooks-claude (Agno 2.8.0 source)

### basic.py — FIXED

**Fix:** both tasks saturated at k=4, so the low-vs-high policy diff was all +0.00.
Replaced `product-d` with a calibrated chain (`product-b`, expected 10481347) so the
low-effort baseline reliably fails some attempts; the high-effort candidate then
shows a real improvement.

**Grid (k=4):** baseline `product-a` 3/4 (0.75) and `product-b` 3/4 (0.75), both
zones; candidate 4/4 each; diff `product-a` +0.25 improved, `product-b` +0.25
improved.

`mismatch_guard.py` (raises the expected MismatchError; product-a 0.75 zone) and
`task_subset.py` (a=0.50, b=0.50) re-ran clean and unchanged.

---

Tested 2026-07-20 with `gpt-5.5`; the baseline used low reasoning effort and the
candidate used high reasoning effort where noted.

### basic.py

**Status:** PASS

**Description:** Compared low- and high-reasoning policies on the same
environment and rendered a valid `EnvironmentDiff`.

**Result:** Low effort: `product-a` 1/4 (0.25), `product-d` 4/4 (1.00). High
effort: both rows 4/4 (1.00). The diff reported `product-a` improved by +0.75
and correctly marked the policy as changed.

---

### task_subset.py

**Status:** PASS

**Description:** Compared a high-effort task subset with a full low-effort
baseline while preserving environment identity.

**Result:** Baseline: `product-a` 2/4 (0.50), `product-b` 3/4 (0.75).
Candidate subset: `product-a` 4/4 (1.00). The diff reported +0.50 for the shared
row and named `product-b` as baseline-only.

---

### mismatch_guard.py

**Status:** PASS

**Description:** Ran two prompt variants, then verified that the changed
environment fingerprint prevents a policy-style diff.

**Result:** Baseline: `product-a` 4/4 (1.00), `product-c` 4/4 (1.00). Edited
prompt: `product-a` 4/4 (1.00), `product-c` 3/4 (0.75). `MismatchError` was
raised with both divergent environment fingerprints.

---
