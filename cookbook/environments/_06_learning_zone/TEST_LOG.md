# Test Log - _06_learning_zone

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Binary exact-answer rollouts followed by `learning_zone()`.

**Result:** `easy-anchor` passed 4/4 (1.00), `edge-e` 4/4 (1.00), and
`edge-pi` 2/4 (0.50). `learning_zone()` returned only `edge-pi`, matching the
strict binary definition `0 < pass_rate < 1`.

---

### select_middle_band.py

**Status:** PASS

**Description:** Explicit selection of task rows with a strict partial pass rate.

**Result:** `easy` passed 4/4 (1.00), `candidate-a` 3/4 (0.75), and
`candidate-b` 4/4 (1.00). The explicit filter selected only `candidate-a`.

The first edge candidate was too slow: its calibration scored 2/3 with one
unscored 120-second timeout, while the other two rows scored 4/4. It was
replaced with the faster candidate used in the final run.

---

### saturated_tasks.py

**Status:** PASS

**Description:** Comparison of saturated arithmetic with calibrated edge tasks.

**Result:** The two anchors, `saturated-17x23` and `saturated-two-step`, each
passed 4/4 (1.00). The calibrated rows landed at 3/4 (0.75) for
`calibrated-edge-a` and 2/4 (0.50) for `calibrated-edge-b`.

The first live calibration was a failed all-full grid: all four rows scored
4/4. The second edge task was made harder before the successful rerun.

---
