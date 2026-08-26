# Test Log - _21_math

Tested 2026-07-20 live against `gpt-5.5`, agno 2.7.4, using
`.venvs/demo/bin/python` with `OPENAI_API_KEY` loaded from `.envrc`.

### basic.py

**Status:** PASS

**Description:** Saturated multiplication beside a calibrated modular recurrence.

**Result:** 12 attempts in 29s. `single-product` saturated at 6/6, while
`recurrence-8` landed at 5/6 (0.833), producing the intended visible transition from
an easy row to a true learning-zone row.

---

### chained_arithmetic.py

**Status:** PASS

**Description:** Product plus digit-sum, scaling, and remainder transform.

**Result:** 12 attempts in 56s. The shorter chain saturated at 6/6; the longer
16-digit chain split 4/6 (0.667). The explicit `0 < pass_rate < 1` selection returned
only `long-chain`.

---

### recurrence_boundary.py

**Status:** PASS

**Description:** Eight-, nine-, and ten-round nonlinear recurrence ladder.

**Result:** 18 attempts in 82s, all scored. `rounds-8` was 3/6 (0.500),
`rounds-9` was 3/6 (0.500), and `rounds-10` was 4/6 (0.667). Every row occupied
the middle band without the 30s-plus incomplete behavior seen in the discarded
11- and 15-round calibration tasks.

---
