# Test Log - _28_ci_gating

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Aggregate `summary()` gate with an unscored-attempt guard.

**Result:** The final normal live run completed 8/8 scored attempts in 50
seconds. `rounds-eight` passed 0/4 (0.00) and `rounds-nine` 2/4 (0.50), giving
an aggregate 0.25 against the 0.60 floor. It printed `gate decision: FAIL` and
exited successfully with enforcement disabled.

The explicit enforcement check used `--enforce --minimum-pass-rate 1.0` and
observed 3/4 (0.75) on both rows. It printed FAIL and exited with status 1;
the surrounding test command verified that expected status and completed
successfully.

---

### per_task_floor.py

**Status:** PASS

**Description:** Per-task pass-rate floor over calibrated recurrence tasks.

**Result:** The enforced live run completed 12/12 scored attempts in 68 seconds.
`easy-anchor` passed 4/4 (1.00), `rounds-eight` 1/4 (0.25), and `rounds-ten`
0/4 (0.00). With `--minimum-task-rate 1.0`, the gate named both recurrence
tasks as violations and exited with status 1; the surrounding command asserted
that expected status.

---

### baseline_regression.py

**Status:** PASS

**Description:** Saved baseline and `EnvironmentDiff` regression gate.

**Result:** The enforced final run saved and reloaded a high-reasoning baseline
at 4/4 (1.00) on both tasks. The low-reasoning candidate scored 3/4 (0.75) on
`rounds-eight` and 2/4 (0.50) on `rounds-nine`, so `EnvironmentDiff` reported
regressions of -0.25 and -0.50. With `--maximum-drop 0.0`, the gate named both
tasks, reported zero unscored attempts on both sides, and exited with status 1;
the surrounding command asserted that expected status. Baseline and candidate
runs took 131 and 77 seconds respectively.

**Calibration:** An earlier medium-reasoning candidate at the 3000-token cap
was discarded after six incomplete-response warnings. The first enforcement
probe with low reasoning on both sides produced 2/4 (0.50) on every row, so the
zero-drop gate correctly passed and exited 0. The final high-versus-low policy
comparison removed that tie and supplied the exercised regression path.

---
