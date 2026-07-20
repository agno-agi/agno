# Test Log - _16_policy_settings

Tested 2026-07-20 with `gpt-5.5`, comparing low and high reasoning effort.

### basic.py

**Status:** PASS

**Description:** Applied a high-reasoning model override to the same environment
and rendered a policy-only diff.

**Result:** Low: `product-a` 3/4 (0.75), `product-d` 1/4 (0.25). High: both
rows 4/4 (1.00). The diff reported +0.25 and +0.75 with policy changed.

---

### reasoning_effort.py

**Status:** PASS

**Description:** Inspected the fingerprint split and per-task deltas across low
and high reasoning effort.

**Result:** Low: `product-a` 3/4 (0.75), `product-e` 3/4 (0.75). High: both
rows 4/4 (1.00). Environment fingerprints matched, policy fingerprints differed,
and each task improved by +0.25.

---
