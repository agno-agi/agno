# Test Log - _19_error_analysis

## Re-test 2026-07-20 — fix/cookbooks-claude (Agno 2.8.0 source)

All three files already demonstrated their claim (a real zone plus unscored evidence
kept separate from wrong answers). Hardened the three custom scorers so a truncated
attempt (`run.content is None` after `max_output_tokens`) raises a clear
`ValueError("no parsed output: hit max_output_tokens")` instead of a cryptic
`'NoneType' object has no attribute 'value'`. The runner still records the attempt
unscored — a no-answer, never a wrong answer — counts are unchanged, and errors()
now reads honestly.

### basic.py — hardened; PASS

**Grid (k=8):** `hard-product` 5/8 (0.62, zone; 2 truncated → unscored);
`scorer-outage` 0/0 (8 unscored, deliberate RuntimeError).

### scorer_errors.py — hardened; PASS

**Grid (k=8):** `hard-product` 3/6 scored (0.50, zone; 2 unscored via the new clear
ValueError); `missing-gold` 8 unscored (missing-expected ValueError).

### stop_reasons.py — hardened; PASS

**Grid (k=8):** `hard-product` 5/8 (0.62, zone); `verifier-error` 8 unscored.
StopReason counts: completed 16, error/timeout/cancelled/paused 0.

---

Tested 2026-07-20 live against `gpt-5.5`, agno 2.7.4, using
`.venvs/demo/bin/python` with `OPENAI_API_KEY` loaded from `.envrc`.

### basic.py

**Status:** PASS

**Description:** Difficult typed arithmetic plus a deliberately raising scorer row,
followed by `summary()` and `errors()`.

**Result:** 16 attempts in 55s. `hard-product` landed in the learning zone at
5/8 (0.625); `scorer-outage` retained 8/8 attempts as unscored, each with the
deliberate `RuntimeError`. The aggregate pass rate was 0.625 over 8 scored attempts,
not 5/16, confirming that unscored evidence is excluded from the denominator.

---

### scorer_errors.py

**Status:** PASS

**Description:** Per-attempt scorer exceptions captured without aborting other tasks.

**Result:** 16 attempts in 56s. `hard-product` produced a genuine middle band at
7/8 (0.875), while `missing-gold` was 0/0 scored with 8 unscored attempts. All eight
captured errors named the deliberate `ValueError`; the healthy task remained complete.

---

### stop_reasons.py

**Status:** PASS

**Description:** Public `StopReason` counts over completed and scorer-error attempts.

**Result:** Final run after adding public `TaskResult`/`AttemptResult` annotations:
16 attempts in 62s. `hard-product` was 4/6 scored (0.667) with two output-limit
responses that reached the scorer without typed content; `verifier-error` was 0/0
scored with eight deliberate scorer exceptions. All 16 run stop reasons were
`completed`, while 10 scores were absent. This demonstrates why stop reason, score
presence, and the error field must be inspected together.

---
