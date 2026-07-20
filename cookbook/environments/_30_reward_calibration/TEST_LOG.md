# Test Log - _30_reward_calibration

Tested 2026-07-21 with `.venvs/demo/bin/python`. Both files are offline and
deterministic; no model provider was called and no API key was set.

### basic.py

**Status:** PASS

**Description:** Calibrated a deliberately lenient scorer (`str(expected) in
run.content`) against eight hand-labelled traces, including two traps that
contain the right digits while being wrong answers ("It is not 42.", "42000")
and one correct answer the scorer cannot see ("forty-two").

**Result:** 8 traces, 8 scored, 0 scorer errors. Agreement 0.62, false positive
rate 0.50, false negative rate 0.25. The three disagreements were reported
individually with their direction: traces 3 and 4 passed what should fail,
trace 5 failed what should pass. The denominators behave as specified — the FP
rate is over gold-negatives (2/4) and the FN rate over gold-positives (1/4).

---

### audit_gap.py

**Status:** PASS

**Description:** Ran `ImprovementLoop.run(rounds=3)` with an `audit_scorer`
against a scripted model that leans progressively harder on a shortcut phrasing
the training scorer accepts and the audit rejects.

**Result:** The gap widened exactly as the reward-hacking signal predicts.

| round | train | audit | gap |
|---|---|---|---|
| 1 | 0.50 | 0.33 | +0.17 |
| 2 | 1.00 | 0.33 | +0.67 |
| 3 | converged: saturated (no tuned rollout, so no audit reading) |

Round 3 short-circuited because the tuned model saturated the training scorer,
which is the correct behaviour: with an empty export there is nothing to train
on and `reward_hack` is `None` rather than a fabricated number. The report
carried a non-null `audit_scorer_digest`, so the reading is attributable to a
specific verifier.

---
