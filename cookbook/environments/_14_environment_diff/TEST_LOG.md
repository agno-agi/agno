# Test Log - _14_environment_diff

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
