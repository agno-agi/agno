# Test Log - _23_code_fixes

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Constrained safe patch selection at K=6.

**Result:** Final live run after adding the previously missing shared-task
cancellation regression case: `shared-task-cancellation` 6/6,
`race-safe-path-open` 5/6, `dst-fold-timeline` 6/6,
`canonical-caseless-key` 6/6, and `weakref-finalizer-capture` 6/6. Earlier
three-choice and five-choice versions saturated at 6/6 on every row. Requiring
the exact minimal regression-test ids as well as the patch id exposed the final
5/6 middle band.

---

### patch_selection.py

**Status:** PASS

**Description:** Competing patches with concurrency and protocol invariants at K=6.

**Result:** `single-flight-cache` 6/6, `stream-timeout` 5/6,
`conditional-update` 6/6, `nested-exception-group` 6/6, and
`float-cache-key` 6/6. Patch-id-only grids saturated even after two harder
cases were added. Scoring the plausible runner-up as evidence exposed the 5/6
learning-zone row.

---

### regression_tests.py

**Status:** PASS

**Description:** Exact minimal regression-test selection at K=8.

**Result:** `cursor-boundary` 8/8, `single-flight` 8/8, `atomic-write` 8/8,
and `overlapping-coverage` 6/8. The initial three tasks, a 10-invariant cover,
and a 16-invariant cover all saturated. A 20-invariant, 25-test unique
minimum-cover task produced the observed partial row at K=8. A mutation-budget
candidate also saturated and was removed rather than presented as useful
evidence.

---
