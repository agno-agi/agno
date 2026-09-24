# Test Log - _20_report_drilldown

Tested 2026-07-20 live against `gpt-5.5`, agno 2.7.4, using
`.venvs/demo/bin/python` with `OPENAI_API_KEY` loaded from `.envrc`.

### basic.py

**Status:** PASS

**Description:** Mixed arithmetic rollout followed by the default failed-attempt
report.

**Result:** 8 attempts in 66s. `hard-product` was 5/6 scored (0.833), a genuine
middle band, with two output-limit responses retained as unscored. The default report
showed exactly those two unscored attempts and the one scored failure, including token
counts and the wrong returned value.

---

### failed_only.py

**Status:** PASS

**Description:** Failed-only report with a two-attempt display cap.

**Result:** 8 attempts in 68s. `hard-product` was again 5/6 scored (0.833) with
two unscored output-limit responses. The cap displayed two investigation rows and
printed `... 1 more`, proving that report capping does not hide the omitted count.

---

### single_attempt.py

**Status:** PASS

**Description:** Programmatic selection and full rendering of one failed attempt.

**Result:** Final live run after guarding the saturated-grid case: 8 attempts in
70s. `hard-product` split 4/7 scored (0.571), with one output-limit response
retained as unscored. The file selected attempt 1, a scored failure, and
`print_attempt()` rendered its input, expected value, stop reason, score,
duration, limit flag, and full typed response (`20420655` instead of
`20944939`). If no scored failure exists, the new guard prints an explicit
recalibration message instead of raising `StopIteration`.

---
